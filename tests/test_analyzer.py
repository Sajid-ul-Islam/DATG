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
