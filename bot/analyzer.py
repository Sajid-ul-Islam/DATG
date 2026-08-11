import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server environments
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Tuple, List, Optional, Dict, Any

# Set modern plotting style
plt.style.use('ggplot')
sns.set_theme(style="whitegrid", palette="muted")


class DataAnalyzer:
    """
    Analyzes CSV/Excel datasets and produces text summaries and visualizations.
    """

    @staticmethod
    def load_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
        """
        Loads bytes into a pandas DataFrame based on file extension.
        """
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
                df = pd.read_excel(buffer)
            except Exception as e:
                raise ValueError(f"Failed to parse Excel file: {str(e)}")
        else:
            raise ValueError(f"Unsupported file format for file: {filename}. Please upload a .csv, .xlsx, or .xls file.")

        if df.empty:
            raise ValueError("The uploaded dataset is empty.")

        return df

    @staticmethod
    def generate_summary(df: pd.DataFrame, filename: str) -> str:
        """
        Generates a markdown text summary of the DataFrame.
        """
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

        return "\n".join(lines)

    @staticmethod
    def generate_visualizations(df: pd.DataFrame) -> List[Tuple[io.BytesIO, str]]:
        """
        Generates analysis charts (histograms, correlation heatmaps, bar charts).
        Returns a list of (BytesIO buffer, caption) tuples.
        """
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

        return charts
