import io
import pytest
import pandas as pd
from bot.analyzer import DataAnalyzer


@pytest.fixture
def sample_csv_bytes():
    df = pd.DataFrame({
        'Age': [25, 30, 35, 40, None, 50],
        'Salary': [50000, 60000, 75000, 90000, 110000, 125000],
        'Department': ['HR', 'IT', 'IT', 'Finance', 'Finance', 'IT']
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture
def sample_excel_bytes():
    df = pd.DataFrame({
        'Score': [85.5, 92.0, 78.5, 88.0],
        'Passed': [True, True, False, True],
        'Student': ['Alice', 'Bob', 'Charlie', 'David']
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()


def test_load_csv_dataframe(sample_csv_bytes):
    df = DataAnalyzer.load_dataframe(sample_csv_bytes, "test_data.csv")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 6
    assert list(df.columns) == ['Age', 'Salary', 'Department']


def test_load_excel_dataframe(sample_excel_bytes):
    df = DataAnalyzer.load_dataframe(sample_excel_bytes, "test_data.xlsx")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 4
    assert 'Score' in df.columns


def test_generate_summary(sample_csv_bytes):
    df = DataAnalyzer.load_dataframe(sample_csv_bytes, "test_data.csv")
    summary = DataAnalyzer.generate_summary(df, "test_data.csv")
    
    assert "test_data.csv" in summary
    assert "Rows**: 6" in summary
    assert "Columns**: 3" in summary
    assert "Missing Values" in summary
    assert "Age" in summary
    assert "Salary" in summary


def test_generate_visualizations(sample_csv_bytes):
    df = DataAnalyzer.load_dataframe(sample_csv_bytes, "test_data.csv")
    charts = DataAnalyzer.generate_visualizations(df)
    
    # Expecting histogram grid, correlation heatmap, and category bar chart
    assert len(charts) > 0
    for buf, caption in charts:
        assert isinstance(buf, io.BytesIO)
        assert len(buf.getvalue()) > 0
        # Check PNG header magic bytes
        assert buf.getvalue().startswith(b'\x89PNG\r\n\x1a\n')


def test_empty_csv_error():
    empty_buf = io.BytesIO(b"")
    with pytest.raises(ValueError, match="empty"):
        DataAnalyzer.load_dataframe(empty_buf.getvalue(), "empty.csv")


def test_unsupported_file_format():
    buf = io.BytesIO(b"hello world")
    with pytest.raises(ValueError, match="Unsupported file format"):
        DataAnalyzer.load_dataframe(buf.getvalue(), "test.pdf")


# ──────────────────────────────────────────────────────────────────────────────
# New Feature Tests (implementation_plan.md)
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_outliers_text():
    df = pd.DataFrame({
        'normal': [1, 2, 3, 4, 5, 6, 7, 8],
        'with_outlier': [1, 2, 3, 4, 5, 6, 7, 100],
    })
    report = DataAnalyzer.detect_outliers_text(df)
    assert 'with_outlier' in report
    assert 'outlier' in report.lower()
    assert 'normal' not in report


def test_detect_outliers_no_outliers_returns_empty():
    df = pd.DataFrame({'x': [1, 2, 3, 4, 5, 6, 7, 8]})
    assert DataAnalyzer.detect_outliers_text(df) == ''


def test_detect_outliers_skips_non_numeric():
    df = pd.DataFrame({'category': ['a', 'b', 'c', 'd']})
    assert DataAnalyzer.detect_outliers_text(df) == ''


def test_detect_date_columns():
    df = pd.DataFrame({
        'date': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
        'value': [1, 2, 3, 4, 5],
    })
    assert 'date' in DataAnalyzer.detect_date_columns(df)
    assert 'value' not in DataAnalyzer.detect_date_columns(df)


def test_detect_date_columns_none():
    df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})
    assert DataAnalyzer.detect_date_columns(df) == []


def test_detect_date_columns_ignores_all_null():
    df = pd.DataFrame({'notes': [None, None, None], 'value': [1, 2, 3]})
    assert DataAnalyzer.detect_date_columns(df) == []


def test_generate_timeseries_charts():
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=10),
        'value': range(10),
    })
    charts = DataAnalyzer.generate_timeseries_charts(df)
    assert len(charts) == 1
    buf, caption = charts[0]
    assert buf.getvalue().startswith(b'\x89PNG\r\n\x1a\n')
    assert 'date' in caption


def test_generate_timeseries_charts_no_date():
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
    assert DataAnalyzer.generate_timeseries_charts(df) == []


def test_generate_timeseries_charts_all_nat():
    df = pd.DataFrame({
        'date': pd.to_datetime([None, None, None]),
        'value': [1, 2, 3],
    })
    assert DataAnalyzer.generate_timeseries_charts(df) == []


def test_dataframe_to_markdown():
    df = pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})
    table = DataAnalyzer.dataframe_to_markdown(df)
    assert 'a' in table
    assert 'b' in table
    assert '1' in table
    assert 'y' in table


def test_dataframe_to_markdown_respects_max_rows():
    df = pd.DataFrame({'x': list(range(25))})
    table = DataAnalyzer.dataframe_to_markdown(df, max_rows=10)
    # Table should not contain every row value
    assert '24' not in table


def test_generate_ai_summary_without_key():
    df = pd.DataFrame({'x': [1, 2, 3]})
    assert DataAnalyzer.generate_ai_summary(df, 'test.csv', '') is None


def test_generate_summary_includes_new_sections():
    df = pd.DataFrame({
        'date': ['2024-01-01'] * 5,
        'value': [1, 2, 3, 100, 5],
    })
    summary = DataAnalyzer.generate_summary(df, 'test.csv')
    assert 'Outlier Report' in summary
    assert 'Date columns detected' in summary


# ──────────────────────────────────────────────────────────────────────────────
# /stats — generate_column_stats
# ──────────────────────────────────────────────────────────────────────────────


def test_generate_column_stats_numeric():
    df = pd.DataFrame({'Salary': [50000, 60000, 75000, 90000, 110000, 125000]})
    stats = DataAnalyzer.generate_column_stats(df, 'Salary')
    assert 'Salary' in stats
    assert 'Mean:' in stats
    assert 'Min:' in stats
    assert 'Max:' in stats
    assert 'Median:' in stats


def test_generate_column_stats_categorical():
    df = pd.DataFrame({'Department': ['HR', 'IT', 'IT', 'Finance', 'Finance', 'IT']})
    stats = DataAnalyzer.generate_column_stats(df, 'Department')
    assert 'Unique:' in stats
    assert 'Top:' in stats
    assert 'IT' in stats


def test_generate_column_stats_datetime():
    df = pd.DataFrame({'date': pd.to_datetime(['2024-01-01', '2024-01-05', '2024-01-10'])})
    stats = DataAnalyzer.generate_column_stats(df, 'date')
    assert '2024-01-01' in stats
    assert '2024-01-10' in stats


def test_generate_column_stats_all_columns():
    df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})
    stats = DataAnalyzer.generate_column_stats(df)
    assert 'a' in stats
    assert 'b' in stats


def test_generate_column_stats_unknown_column_raises():
    df = pd.DataFrame({'a': [1, 2, 3]})
    with pytest.raises(ValueError, match="not found"):
        DataAnalyzer.generate_column_stats(df, 'nope')


def test_generate_column_stats_all_null():
    df = pd.DataFrame({'notes': [None, None, None]})
    stats = DataAnalyzer.generate_column_stats(df, 'notes')
    assert 'No values' in stats


def test_generate_column_stats_single_value():
    df = pd.DataFrame({'x': [42]})
    stats = DataAnalyzer.generate_column_stats(df, 'x')
    assert 'nan' not in stats
    assert '42' in stats


def test_generate_column_stats_large_numbers_no_sci():
    df = pd.DataFrame({'Salary': [50000, 60000, 75000]})
    stats = DataAnalyzer.generate_column_stats(df, 'Salary')
    assert 'e+' not in stats
    assert '50,000' in stats
    assert '60,000' in stats


# ──────────────────────────────────────────────────────────────────────────────
# /sort — sort_dataframe
# ──────────────────────────────────────────────────────────────────────────────


def test_sort_dataframe_ascending():
    df = pd.DataFrame({'Age': [30, 25, 40], 'Name': ['b', 'a', 'c']})
    out = DataAnalyzer.sort_dataframe(df, 'Age')
    assert out['Age'].tolist() == [25, 30, 40]
    assert out['Name'].tolist() == ['a', 'b', 'c']


def test_sort_dataframe_descending():
    df = pd.DataFrame({'Age': [30, 25, 40]})
    out = DataAnalyzer.sort_dataframe(df, 'Age', ascending=False)
    assert out['Age'].tolist() == [40, 30, 25]


def test_sort_dataframe_strings():
    df = pd.DataFrame({'City': ['NY', 'LA', 'SF']})
    out = DataAnalyzer.sort_dataframe(df, 'City')
    assert out['City'].tolist() == ['LA', 'NY', 'SF']


def test_sort_dataframe_does_not_mutate_original():
    df = pd.DataFrame({'Age': [30, 25, 40]})
    DataAnalyzer.sort_dataframe(df, 'Age')
    assert df['Age'].tolist() == [30, 25, 40]


def test_sort_dataframe_unknown_column_raises():
    df = pd.DataFrame({'Age': [30, 25, 40]})
    with pytest.raises(ValueError, match="not found"):
        DataAnalyzer.sort_dataframe(df, 'nope')


def test_sort_dataframe_mixed_types_raises():
    df = pd.DataFrame({'val': [1, 'a', 2]})
    with pytest.raises(ValueError, match="not comparable"):
        DataAnalyzer.sort_dataframe(df, 'val')


def test_sort_dataframe_nan_sorts_last():
    df = pd.DataFrame({'Age': [30, None, 25]})
    out = DataAnalyzer.sort_dataframe(df, 'Age')
    assert out['Age'].iloc[0] == 25
    assert out['Age'].iloc[1] == 30
    assert pd.isna(out['Age'].iloc[2])

    out_desc = DataAnalyzer.sort_dataframe(df, 'Age', ascending=False)
    assert out_desc['Age'].iloc[0] == 30
    assert out_desc['Age'].iloc[1] == 25
    assert pd.isna(out_desc['Age'].iloc[2])
