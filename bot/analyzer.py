from __future__ import annotations

import io
import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u2190-\u21FF]"
)


def _strip_emoji(text: str) -> str:
    """Remove emoji/symbol glyphs that reportlab's built-in fonts can't render."""
    return _EMOJI_RE.sub("", text)


def _md_to_plain(text: str) -> str:
    """Strip common markdown markers so text renders cleanly in PDFs/images."""
    text = re.sub(r"```", "", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return text

# Heavy data-science libraries (pandas, numpy, matplotlib, seaborn) are imported
# lazily on first use so that importing this module stays cheap. This keeps
# serverless cold starts (e.g. on Vercel) fast — importing these libraries can
# take several seconds, and most requests (like /help) never touch a dataset.
_pd = _np = _plt = _sns = None


def _lazy_libs() -> tuple:
    """
    Import pandas/numpy/matplotlib/seaborn once, on first use.

    Returns (pd, np, plt, sns). Matplotlib's Agg backend and the shared
    plotting style are configured here, when the libraries are actually needed.
    """
    global _pd, _np, _plt, _sns
    if _pd is None:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend for server environments
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import seaborn as sns

        # Set modern plotting style (once, when the libs first load)
        plt.style.use('ggplot')
        sns.set_theme(style="whitegrid", palette="muted")

        _pd, _np, _plt, _sns = pd, np, plt, sns
    return _pd, _np, _plt, _sns


class DataAnalyzer:
    """
    Analyzes CSV/Excel datasets and produces text summaries and visualizations.
    """

    @staticmethod
    def load_dataframe(file_bytes: bytes, filename: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        Loads bytes into a pandas DataFrame based on file extension.

        For Excel files, `sheet_name` selects a specific tab; when None the
        first sheet is used.
        """
        pd, np, plt, sns = _lazy_libs()
        buffer = io.BytesIO(file_bytes)
        filename_lower = filename.lower()

        if filename_lower.endswith('.csv'):
            # Try UTF-8 first, fallback to latin-1 if decoding fails
            try:
                df = pd.read_csv(buffer, encoding='utf-8')
            except pd.errors.EmptyDataError:
                raise ValueError("The uploaded dataset is empty.")
            except UnicodeDecodeError:
                buffer.seek(0)
                try:
                    df = pd.read_csv(buffer, encoding='latin-1')
                except pd.errors.EmptyDataError:
                    raise ValueError("The uploaded dataset is empty.")
        elif filename_lower.endswith(('.xlsx', '.xls')):
            try:
                # None means "first sheet" (passing None to read_excel would
                # return a dict of all sheets, so map it to 0 explicitly)
                df = pd.read_excel(buffer, sheet_name=sheet_name if sheet_name is not None else 0)
            except ValueError as e:
                if sheet_name is not None:
                    raise ValueError(
                        f"Sheet `{sheet_name}` not found in the workbook. "
                        "Use `/sheets` to list available tabs."
                    ) from e
                raise ValueError(f"Failed to parse Excel file: {str(e)}") from e
            except Exception as e:
                raise ValueError(f"Failed to parse Excel file: {str(e)}")
        else:
            raise ValueError(
                f"Unsupported file format for file: {filename}. "
                "Please upload a .csv, .xlsx, or .xls file."
            )

        if df.empty:
            raise ValueError("The uploaded dataset is empty.")

        return df

    @staticmethod
    def list_sheets(file_bytes: bytes, filename: str) -> List[str]:
        """
        Returns the sheet/tab names of an Excel workbook (empty for CSV).
        """
        if not filename.lower().endswith(('.xlsx', '.xls')):
            return []
        pd, np, plt, sns = _lazy_libs()
        try:
            workbook = pd.ExcelFile(io.BytesIO(file_bytes))
            return list(workbook.sheet_names)
        except Exception:
            return []

    @staticmethod
    def generate_summary(df: pd.DataFrame, filename: str) -> str:
        """
        Generates a markdown text summary of the DataFrame.
        """
        pd, np, plt, sns = _lazy_libs()
        rows, cols = df.shape
        total_cells = rows * cols
        total_nulls = int(df.isnull().sum().sum())
        null_percent = (total_nulls / total_cells * 100) if total_cells > 0 else 0.0
        memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)

        lines = [
            f"📊 **Data Summary for `{filename}`**\n",
            f"• **Rows**: {rows:,}",
            f"• **Columns**: {cols:,}",
            f"• **Missing Values**: {total_nulls:,} ({null_percent:.1f}%)",
            f"• **Memory Footprint**: {memory_mb:.2f} MB\n",
            "📋 **Column Details:**"
        ]

        # Column info table
        col_info_rows = []
        for col in df.columns[:15]:  # Limit to first 15 columns for chat clarity
            dtype_str = str(df[col].dtype)
            null_count = int(df[col].isnull().sum())
            col_info_rows.append(f"• `{col}` ({dtype_str}): {null_count} missing")

        lines.extend(col_info_rows)

        if len(df.columns) > 15:
            lines.append(f"  *... and {len(df.columns) - 15} more columns*")

        # Numeric Statistics Summary
        numeric_df = df.select_dtypes(include=[np.number])
        if not numeric_df.empty:
            lines.append("\n📈 **Numeric Statistics (Sample):**")
            stats = numeric_df.describe().T[['mean', '50%', 'std', 'min', 'max']]
            stats.columns = ['Mean', 'Median', 'Std', 'Min', 'Max']

            # Format stats into monospaced block
            lines.append("```")
            lines.append(stats.round(2).to_string())
            lines.append("```")

        # Outlier detection summary
        outlier_text = DataAnalyzer.detect_outliers_text(df)
        if outlier_text:
            lines.append(outlier_text)

        # Time-series detection note
        date_cols = DataAnalyzer.detect_date_columns(df)
        if date_cols:
            cols_str = ", ".join(f"`{c}`" for c in date_cols)
            lines.append(f"\n📅 **Date columns detected:** {cols_str} — time-series charts generated below.")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Outlier Detection
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def detect_outliers_text(df: pd.DataFrame) -> str:
        """
        Uses the IQR method to detect outliers in each numeric column.
        Returns a formatted markdown string, or empty string if none found.
        """
        pd, np, plt, sns = _lazy_libs()
        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty:
            return ""

        outlier_lines = []
        for col in numeric_df.columns[:10]:  # Cap at 10 cols
            series = numeric_df[col].dropna()
            if len(series) < 4:
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            n_outliers = int(((series < lower) | (series > upper)).sum())
            pct = n_outliers / len(series) * 100
            if n_outliers > 0:
                outlier_lines.append(f"  • `{col}`: {n_outliers:,} outliers ({pct:.1f}%)")

        if not outlier_lines:
            return ""

        return "\n⚠️ **Outlier Report (IQR method):**\n" + "\n".join(outlier_lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Time-Series Detection
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def detect_date_columns(df: pd.DataFrame) -> List[str]:
        """
        Attempts to identify date/datetime columns in the DataFrame.
        Returns a list of detected column names.
        """
        pd, np, plt, sns = _lazy_libs()
        date_cols = []
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                date_cols.append(col)
            elif pd.api.types.is_string_dtype(df[col]):
                # Try parsing a sample
                sample = df[col].dropna().head(20)
                if len(sample) == 0:
                    continue
                try:
                    parsed = pd.to_datetime(sample, errors='coerce')
                    if parsed.notna().sum() >= len(sample) * 0.8:
                        date_cols.append(col)
                except Exception:
                    pass
        return date_cols

    @staticmethod
    def generate_timeseries_charts(df: pd.DataFrame) -> List[Tuple[io.BytesIO, str]]:
        """
        Generates line charts for each detected date column vs numeric columns.
        Returns a list of (BytesIO buffer, caption) tuples.
        """
        pd, np, plt, sns = _lazy_libs()
        charts: List[Tuple[io.BytesIO, str]] = []
        date_cols = DataAnalyzer.detect_date_columns(df)
        numeric_cols = df.select_dtypes(include=[np.number]).columns[:4]  # Max 4 numeric

        if not date_cols or numeric_cols.empty:
            return charts

        date_col = date_cols[0]  # Use the first date column

        # Parse dates if not already
        try:
            date_series = pd.to_datetime(df[date_col], errors='coerce')
        except Exception:
            return charts

        plot_df = df.copy()
        plot_df['__date__'] = date_series
        plot_df = plot_df.dropna(subset=['__date__']).sort_values('__date__')

        if plot_df.empty:
            return charts

        fig, axes = plt.subplots(
            len(numeric_cols), 1,
            figsize=(10, 3 * len(numeric_cols)),
            sharex=True
        )
        if len(numeric_cols) == 1:
            axes = [axes]

        for i, num_col in enumerate(numeric_cols):
            grouped = plot_df.groupby('__date__')[num_col].mean()
            axes[i].plot(grouped.index, grouped.values, linewidth=1.8, color="#3498db")
            axes[i].fill_between(grouped.index, grouped.values, alpha=0.15, color="#3498db")
            axes[i].set_title(f"{num_col} over time", fontsize=10, fontweight='bold')
            axes[i].set_ylabel(num_col, fontsize=8)

        axes[-1].set_xlabel(date_col)
        plt.suptitle(f"Time-Series Analysis (by {date_col})", fontsize=12, fontweight='bold', y=1.01)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        charts.append((buf, f"📅 Time-Series trends by `{date_col}`"))
        return charts

    # ──────────────────────────────────────────────────────────────────────────
    # AI Insight Summary
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_ai_summary(df: pd.DataFrame, filename: str, openai_api_key: str) -> Optional[str]:
        """
        Uses OpenAI gpt-4o-mini to generate a plain-English data insight summary.
        Returns None if the API key is missing or the call fails.
        """
        if not openai_api_key:
            return None

        try:
            from openai import OpenAI  # Lazy import — only needed if key is present

            pd, np, plt, sns = _lazy_libs()
            rows, cols = df.shape
            numeric_df = df.select_dtypes(include=[np.number])
            col_list = ", ".join(df.columns[:20].tolist())

            stats_snippet = ""
            if not numeric_df.empty:
                stats = numeric_df.describe().T[['mean', '50%', 'std', 'min', 'max']]
                stats.columns = ['Mean', 'Median', 'Std', 'Min', 'Max']
                stats_snippet = stats.round(2).to_string()

            prompt = (
                f"You are a data analyst. Analyze the following dataset statistics and provide "
                f"3-5 concise, actionable insights in plain English. Be specific and avoid generic statements.\n\n"
                f"File: {filename}\n"
                f"Rows: {rows:,}, Columns: {cols}\n"
                f"Column names: {col_list}\n"
                f"Numeric stats:\n{stats_snippet}\n\n"
                f"Provide insights as bullet points."
            )

            client = OpenAI(api_key=openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()

        except Exception:
            logger.warning("AI insight summary failed for %s", filename, exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Visualizations
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_visualizations(df: pd.DataFrame) -> List[Tuple[io.BytesIO, str]]:
        """
        Generates analysis charts (histograms, correlation heatmaps, bar charts).
        Returns a list of (BytesIO buffer, caption) tuples.
        """
        pd, np, plt, sns = _lazy_libs()
        charts: List[Tuple[io.BytesIO, str]] = []
        numeric_df = df.select_dtypes(include=[np.number])
        cat_df = df.select_dtypes(include=['object', 'category'])

        # 1. Numeric Distributions Grid
        if not numeric_df.empty:
            num_cols = numeric_df.columns[:9]  # Up to 9 numeric columns for grid
            n = len(num_cols)
            cols_grid = min(3, n)
            rows_grid = (n + cols_grid - 1) // cols_grid

            fig, axes = plt.subplots(rows_grid, cols_grid, figsize=(4 * cols_grid, 3 * rows_grid))
            if n == 1:
                axes_flat = [axes]
            else:
                axes_flat = axes.flatten() if hasattr(axes, 'flatten') else [axes]

            for i, col in enumerate(num_cols):
                sns.histplot(numeric_df[col].dropna(), kde=True, ax=axes_flat[i], color="#3498db")
                axes_flat[i].set_title(f"Distribution: {col}", fontsize=10, fontweight='bold')
                axes_flat[i].set_xlabel("")
                axes_flat[i].set_ylabel("")

            # Turn off unused subplots
            for j in range(i + 1, len(axes_flat)):
                fig.delaxes(axes_flat[j])

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            charts.append((buf, "📊 Distribution of Numeric Features"))

        # 2. Correlation Heatmap (if 2+ numeric columns)
        if numeric_df.shape[1] >= 2:
            num_corr_cols = numeric_df.columns[:10]  # Max 10 columns for clean heatmap
            corr = numeric_df[num_corr_cols].corr()

            fig, ax = plt.subplots(figsize=(7, 5))
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="Blues", ax=ax, cbar=True, square=True)
            ax.set_title("Correlation Heatmap", fontsize=12, fontweight='bold')

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            charts.append((buf, "🔥 Correlation Heatmap"))

        # 3. Categorical Top Frequencies (if categorical columns exist)
        if not cat_df.empty:
            cat_col = cat_df.columns[0]
            top_counts = cat_df[cat_col].value_counts().head(8)

            if not top_counts.empty:
                fig, ax = plt.subplots(figsize=(7, 4))
                y_labels = top_counts.index.astype(str)
                sns.barplot(x=top_counts.values, y=y_labels, hue=y_labels, palette="viridis", legend=False, ax=ax)
                ax.set_title(f"Top Values in '{cat_col}'", fontsize=12, fontweight='bold')
                ax.set_xlabel("Count")

                plt.tight_layout()
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                charts.append((buf, f"🏷️ Value counts for '{cat_col}'"))

        # 4. Time-Series charts (if date columns detected)
        ts_charts = DataAnalyzer.generate_timeseries_charts(df)
        charts.extend(ts_charts)

        return charts

    # ──────────────────────────────────────────────────────────────────────────
    # Report Export (Excel / PDF / PNG image)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_excel_report(df: pd.DataFrame, filename: str) -> io.BytesIO:
        """
        Writes the dataset plus a summary sheet and numeric stats into an .xlsx
        workbook. Returns a BytesIO buffer (rewound to 0).
        """
        pd, np, plt, sns = _lazy_libs()
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)

            rows, cols = df.shape
            total_nulls = int(df.isnull().sum().sum())
            summary_rows = [["Metric", "Value"]]
            summary_rows.append(["File", filename])
            summary_rows.append(["Rows", rows])
            summary_rows.append(["Columns", cols])
            summary_rows.append(["Missing values", total_nulls])
            for col in df.columns:
                dtype = str(df[col].dtype)
                nulls = int(df[col].isnull().sum())
                summary_rows.append([f"Column: {col}", f"{dtype} | {nulls} missing"])
            pd.DataFrame(summary_rows[1:], columns=summary_rows[0]).to_excel(
                writer, sheet_name="Summary", index=False
            )

            numeric_df = df.select_dtypes(include=[np.number])
            if not numeric_df.empty:
                numeric_df.describe().T.to_excel(writer, sheet_name="Numeric Stats")
        buf.seek(0)
        return buf

    @staticmethod
    def generate_pdf_report(df: pd.DataFrame, filename: str) -> io.BytesIO:
        """
        Builds a formatted multi-page PDF report: title, dataset summary,
        numeric stats table, and embedded chart images.
        """
        from datetime import datetime, timezone
        from html import escape
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        pd, np, plt, sns = _lazy_libs()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=20, spaceAfter=6)
        meta_style = ParagraphStyle("ReportMeta", parent=styles["BodyText"], fontSize=8.5, textColor=colors.grey, spaceAfter=12)
        h2_style = ParagraphStyle("ReportH2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=12, spaceAfter=5)
        body_style = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontSize=9.5, leading=13)
        mono_style = ParagraphStyle("ReportMono", parent=styles["BodyText"], fontName="Courier", fontSize=8.5, leading=11)

        def _summary_flowables(text: str) -> list:
            """Convert the markdown summary into reportlab flowables."""
            flowables = []
            in_code = False
            for raw in text.splitlines():
                line = raw.rstrip()
                if line.strip() == "```":
                    in_code = not in_code
                    continue
                content = _strip_emoji(escape(_md_to_plain(line)))
                if not content.strip():
                    flowables.append(Spacer(1, 4))
                    continue
                flowables.append(Paragraph(content, mono_style if in_code else body_style))
            return flowables

        story = []
        story.append(Paragraph("Data Analysis Report", title_style))
        story.append(Paragraph(
            f"<b>{escape(filename)}</b> — generated "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            meta_style,
        ))

        story.append(Paragraph("Dataset Summary", h2_style))
        story.extend(_summary_flowables(DataAnalyzer.generate_summary(df, filename)))

        numeric_df = df.select_dtypes(include=[np.number])
        if not numeric_df.empty:
            story.append(Paragraph("Numeric Statistics", h2_style))
            stats = numeric_df.describe().T.round(2)
            data_rows = [[str(i)] + [str(v) for v in row] for i, row in stats.iterrows()]
            table = Table([["Column"] + list(stats.columns)] + data_rows, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
            ]))
            story.append(table)

        charts = DataAnalyzer.generate_visualizations(df)
        if charts:
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
            story.append(Paragraph("Charts", h2_style))
            for chart_buf, caption in charts:
                chart_buf.seek(0)
                img = Image(chart_buf)
                img.drawWidth = doc.width
                img.drawHeight = img.drawWidth * img.imageHeight / img.imageWidth
                story.append(img)
                story.append(Paragraph(_strip_emoji(escape(_md_to_plain(caption))), meta_style))
                story.append(Spacer(1, 10))

        doc.build(story)
        buf.seek(0)
        return buf

    @staticmethod
    def generate_image_report(df: pd.DataFrame, filename: str) -> io.BytesIO:
        """
        Composes a single tall PNG report: colored header, summary text, and
        all generated charts stacked vertically. Returns a BytesIO buffer.
        """
        from datetime import datetime, timezone
        from matplotlib import font_manager
        from PIL import Image as PILImage, ImageDraw, ImageFont

        pd, np, plt, sns = _lazy_libs()
        W = 1240
        MARGIN = 48
        TEXT_W = W - 2 * MARGIN
        HEADER_H = 150
        FOOTER_H = 60
        BG = (255, 255, 255)
        INK = (33, 37, 41)
        ACCENT = (52, 73, 94)
        BLUE = (52, 152, 219)

        def _font(weight: str = "regular", size: int = 20) -> ImageFont.FreeTypeFont:
            path = font_manager.findfont(
                font_manager.FontProperties(family="DejaVu Sans", weight=weight)
            )
            return ImageFont.truetype(path, size)

        title_font = _font("bold", 36)
        meta_font = _font("regular", 17)
        h_font = _font("bold", 24)
        body_font = _font("regular", 19)
        mono_font = _font("regular", 17)

        measure_img = PILImage.new("RGB", (10, 10), BG)
        measure = ImageDraw.Draw(measure_img)

        def _wrap(font, text: str) -> List[str]:
            lines, cur = [], ""
            for word in text.split(" "):
                trial = f"{cur} {word}".strip()
                if measure.textlength(trial, font=font) <= TEXT_W:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            return lines

        def _line_h(font) -> int:
            return font.getbbox("Ag")[3] + 6

        # Classify summary lines into display blocks
        blocks: List[Tuple[str, str]] = []
        in_code = False
        for raw in DataAnalyzer.generate_summary(df, filename).splitlines():
            line = raw.rstrip()
            if line.strip() == "```":
                in_code = not in_code
                continue
            plain = _md_to_plain(line)
            if not plain.strip():
                continue
            plain = _strip_emoji(plain)  # DejaVu Sans has no emoji glyphs
            if in_code:
                blocks.append(("mono", plain))
            elif plain.lstrip().startswith("•"):
                blocks.append(("body", plain))
            else:
                blocks.append(("head", plain))

        block_fonts = {"head": h_font, "body": body_font, "mono": mono_font}

        # Charts, resized to fit the canvas width
        chart_imgs: List[Tuple[PILImage.Image, str]] = []
        for chart_buf, caption in DataAnalyzer.generate_visualizations(df):
            chart_buf.seek(0)
            im = PILImage.open(chart_buf).convert("RGB")
            scale = TEXT_W / im.width
            im = im.resize((int(im.width * scale), int(im.height * scale)), PILImage.LANCZOS)
            chart_imgs.append((im, _strip_emoji(_md_to_plain(caption)).strip()))

        def _block_h(kind: str, text: str) -> int:
            return len(_wrap(block_fonts[kind], text)) * _line_h(block_fonts[kind])

        body_h = sum(_block_h(k, t) + 4 for k, t in blocks) + 24
        charts_h = sum(im.height + 44 for im, _ in chart_imgs)
        total_h = HEADER_H + body_h + charts_h + FOOTER_H

        canvas = PILImage.new("RGB", (W, total_h), BG)
        d = ImageDraw.Draw(canvas)

        # Header band
        d.rectangle([0, 0, W, HEADER_H], fill=ACCENT)
        d.rectangle([0, HEADER_H - 6, W, HEADER_H], fill=BLUE)
        d.text((MARGIN, 30), "Data Analysis Report", font=title_font, fill=(255, 255, 255))
        d.text(
            (MARGIN, 96),
            f"{filename} — generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            font=meta_font, fill=(200, 210, 220),
        )

        y = HEADER_H + 16
        for kind, text in blocks:
            font = block_fonts[kind]
            if kind == "head":
                d.text((MARGIN, y), text, font=font, fill=BLUE)
            else:
                d.text((MARGIN, y), text, font=font, fill=INK)
            y += _block_h(kind, text) + 4
        y += 16

        for im, caption in chart_imgs:
            x = (W - im.width) // 2
            d.rectangle(
                [x - 6, y - 6, x + im.width + 6, y + im.height + 6],
                fill=(245, 247, 250), outline=(210, 215, 222),
            )
            canvas.paste(im, (x, y))
            y += im.height + 10
            d.text((MARGIN, y), caption, font=meta_font, fill=(90, 100, 110))
            y += 36

        d.text(
            (MARGIN, total_h - FOOTER_H + 22),
            "Generated by Telegram Data Analysis Bot",
            font=meta_font, fill=(150, 155, 160),
        )

        out = io.BytesIO()
        canvas.save(out, format="PNG")
        out.seek(0)
        return out

    # ──────────────────────────────────────────────────────────────────────────
    # Row Sorting
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def sort_dataframe(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        """
        Returns a copy of the DataFrame sorted by `column` (original is untouched).
        Raises ValueError if the column is missing or its values can't be compared.
        """
        if column not in df.columns:
            raise ValueError(
                f"Column `{column}` not found. Use `/columns` to see available columns."
            )
        try:
            # Missing values always sort last, regardless of direction
            return df.sort_values(by=column, ascending=ascending, na_position="last")
        except TypeError as e:
            raise ValueError(
                f"Cannot sort by `{column}`: values are not comparable ({str(e)})"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # DataFrame → Markdown Table Utility
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def dataframe_to_markdown(df: pd.DataFrame, max_rows: int = 10) -> str:
        """
        Converts a DataFrame to a monospaced markdown table string.
        Truncates to max_rows rows.
        """
        subset = df.head(max_rows)
        # Use pandas built-in markdown table
        try:
            return subset.to_markdown(index=False)
        except ImportError:
            # Fallback: simple pipe table
            cols = " | ".join(str(c) for c in subset.columns)
            sep = " | ".join(["---"] * len(subset.columns))
            rows_str = "\n".join(
                " | ".join(str(v) for v in row) for row in subset.values
            )
            return f"| {cols} |\n| {sep} |\n" + "\n".join(f"| {r} |" for r in rows_str.split("\n"))

    # ──────────────────────────────────────────────────────────────────────────
    # Per-Column Stats Breakdown
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_column_stats(df: pd.DataFrame, column: Optional[str] = None) -> str:
        """
        Generates a per-column breakdown: count/mean/std/min/median/max for
        numeric columns, unique/top for categoricals, and range for dates.
        If `column` is given, only that column is included.
        Raises ValueError if the requested column does not exist.
        """
        pd, np, plt, sns = _lazy_libs()
        cols = [column] if column else list(df.columns)
        lines = []

        def _fmt(v: float) -> str:
            """Format numbers readably: comma-grouped, no trailing zeros, sci for extremes."""
            if pd.isna(v):
                return "—"
            av = abs(v)
            if av != 0 and (av >= 1e7 or av < 1e-3):
                return f"{v:.4g}"
            return f"{v:,.2f}".rstrip("0").rstrip(".")

        for col in cols:
            if col not in df.columns:
                raise ValueError(f"Column `{col}` not found. Use `/columns` to see available columns.")

            series = df[col]
            count = int(series.notna().sum())
            lines.append(f"**`{col}`** ({series.dtype}) — {count:,} non-null / {len(df):,} rows")

            if pd.api.types.is_numeric_dtype(series):
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No numeric values.")
                    continue
                stats = s.describe()
                lines.append(
                    f"  • Mean: {_fmt(stats['mean'])} | Std: {_fmt(stats['std'])}"
                )
                lines.append(
                    f"  • Min: {_fmt(stats['min'])} | Median: {_fmt(stats['50%'])} | Max: {_fmt(stats['max'])}"
                )
            elif pd.api.types.is_datetime64_any_dtype(series):
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No date values.")
                    continue
                lines.append(
                    f"  • Min: {s.min():%Y-%m-%d %H:%M} | Max: {s.max():%Y-%m-%d %H:%M}"
                )
            else:
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No values.")
                    continue
                unique = s.nunique(dropna=True)
                vc = s.value_counts()
                top = str(vc.index[0])
                top = " ".join(top.split()).replace("`", "'")
                if len(top) > 30:
                    top = top[:27] + "..."
                top_count = int(vc.iloc[0])
                top_pct = top_count / len(s) * 100
                lines.append(
                    f"  • Unique: {unique:,} | Top: `{top}` ({top_count:,} · {top_pct:.1f}%)"
                )

        return "\n".join(lines)
