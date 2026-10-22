import pandas as pd
import numpy as np
import io
import os
import textwrap
from datetime import datetime
from langchain.tools import tool
import dateutil.parser as _dateutil_parser
import re as _re



def _safe_to_datetime(arg, format=None, errors='raise', **kwargs):
    """Robust replacement for pd.to_datetime used within executed operations.

    Tries the requested format first, then falls back to inference/coercion and
    finally to dateutil parsing elementwise. Handles short month-only strings
    like 'Dec' by assuming day=1 and year=2025 as a best-effort fallback.
    
    Args:
        arg: Input to convert to datetime (Series, list, scalar, etc.)
        format: Optional datetime format string
        errors: How to handle parsing errors ('raise', 'coerce', 'ignore')
        **kwargs: Additional arguments to pass to pd.to_datetime
        
    Returns:
        Datetime object, Series, or array depending on input type
    """
    pd_original = pd
    
    try:
        # If a format is provided, prefer that (respect errors setting)
        if format:
            return pd_original.to_datetime(arg, format=format, errors=errors, **kwargs)
        # Try pandas inference with strict errors first
        return pd_original.to_datetime(arg, infer_datetime_format=True, errors=errors, **kwargs)
    except Exception:
        # Try a coercion pass
        try:
            coerced = pd_original.to_datetime(arg, infer_datetime_format=True, errors='coerce', **kwargs)
            # If coercion produced usable results, return them
            if isinstance(coerced, pd_original.Series):
                if not coerced.isna().all():
                    return coerced
            else:
                return coerced
        except Exception:
            pass

    # Last-resort: elementwise parsing with dateutil.parser
    def _parse_one(x):
        if pd_original.isna(x):
            return pd_original.NaT
        s = str(x).strip()
        try:
            return _dateutil_parser.parse(s, dayfirst=False, fuzzy=True)
        except Exception:
            # If the input is a month name like 'Dec', assume day 1 and year 2025
            if _re.fullmatch(r"[A-Za-z]{3,9}", s):
                try:
                    return _dateutil_parser.parse(s + ' 1 2025')
                except Exception:
                    return pd_original.NaT
            return pd_original.NaT

    # Support Series/iterables and scalars
    if hasattr(arg, '__iter__') and not isinstance(arg, (str, bytes)):
        try:
            # Preserve index if it's a Series
            idx = getattr(arg, 'index', None)
            parsed = pd_original.Series([_parse_one(v) for v in list(arg)], index=idx)
            return pd_original.to_datetime(parsed)
        except Exception:
            # fallback to coercion result or NaT series
            return pd_original.to_datetime(pd_original.Series([_parse_one(v) for v in list(arg)]))
    else:
        return _parse_one(arg)


class _PDProxy:
    """Proxy that mirrors pandas but overrides to_datetime with _safe_to_datetime.
    
    This allows executed pandas operations to use pd.to_datetime safely without
    exposing the implementation to code generation risks.
    """
    
    def __init__(self):
        self._pd_original = pd
    
    def __getattr__(self, name):
        if name == 'to_datetime':
            return _safe_to_datetime
        return getattr(self._pd_original, name)


# Tools for Pandas Agent
@tool
async def get_dataframe_info(csv_path: str) -> str:
    """
    Get comprehensive information about the DataFrame structure.
    Returns schema, sample data, date ranges, and unique values for categorical columns.
    """
    csv_path = csv_path.strip()
    if not os.path.exists(csv_path):
        return f"Error: File not found at {csv_path}"

    df = pd.read_csv(csv_path)

    # Check for empty or invalid data early
    is_empty = False
    if df.empty:
        is_empty = True
    elif len(df.columns) == 1 and 'value' in df.columns:
        # Check if the 'value' column contains empty list strings
        try:
            import ast
            first_val = df['value'].iloc[0]
            if isinstance(first_val, str):
                parsed = ast.literal_eval(first_val)
                if isinstance(parsed, list) and len(parsed) == 0:
                    is_empty = True
        except:
            pass

    if is_empty:
        return """EMPTY_DATASET_DETECTED

    The DataFrame contains no actual data to process.
    This typically means the SQL query returned zero rows.

    RECOMMENDED ACTION: Return an empty result immediately without attempting transformations.
    """

    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()

    result = f"""
    DataFrame Structure:
    {info_str}
    Shape: {df.shape[0]} rows × {df.shape[1]} columns
    Columns: {df.columns.tolist()}

    Sample Data (first 3 rows):
    {df.head(3).to_string()}
"""

    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    if len(categorical_cols) > 0:
        result += "\nCategorical Columns (unique values):\n"
        for col in categorical_cols:
            n_unique = df[col].nunique()
            if n_unique <= 50:
                unique_vals = df[col].unique().tolist()[:20]
                result += f"  {col} ({n_unique} unique): {unique_vals}\n"
            else:
                result += f"  {col} ({n_unique} unique values)\n"

    numeric_cols = df.select_dtypes(include=['number']).columns
    if len(numeric_cols) > 0:
        result += f"\nNumeric Columns: {numeric_cols.tolist()}\n"
        result += f"\nNumeric Summary:\n{df[numeric_cols].describe().to_string()}\n"

    return result


@tool
async def execute_pandas_operations(csv_path: str, operations: str, final_output: str = None) -> str:
    """
    Execute pandas operations on the DataFrame from CSV.
    """
    csv_path = csv_path.strip()
    if not os.path.exists(csv_path):
        return f"Error: File not found at {csv_path}"

    df = pd.read_csv(csv_path)

    # Create namespace with safe date parsing
    namespace = {
        'df': df,
        'pd': _PDProxy(),
        'np': np,
        'datetime': datetime,
        'ast': __import__('ast'),
        'json': __import__('json')
    }

    operations_clean = textwrap.dedent(operations).strip('\n')

    # Check for prohibited plotting code
    prohibited_keywords = ['matplotlib', 'plt.', 'seaborn', 'sns.', 'plotly', 'px.', 'go.',
                           'ax.', 'set_title', 'set_xlabel', 'set_ylabel', 'tight_layout',
                           'xticks', 'legend(', 'legend.', 'figure', 'plot(', 'bar(', 'scatter(']
    for keyword in prohibited_keywords:
        if keyword in operations_clean.lower():
            return f"Error: Plotting code detected. Only pandas data transformations are allowed. Found: {keyword}"

    try:
        exec(operations_clean, namespace)
    except SyntaxError as e:
        # Try an automatic repair for unexpected indent errors by left-stripping
        # leading whitespace on each line and retrying. This addresses cases
        # where generated code accidentally includes leading indentation.
        err_text = str(e)
        if 'unexpected indent' in err_text.lower():
            operations_fixed = "\n".join([ln.lstrip() for ln in operations_clean.splitlines()])
            try:
                exec(operations_fixed, namespace)
                operations_clean = operations_fixed
            except Exception as e2:
                return (
                    f"Error executing operations after auto-fix: {str(e2)}\n\n"
                    f"Original operations:\n{operations_clean}\n\n"
                    f"Attempted fixed operations:\n{operations_fixed}"
                )
        else:
            return f"Error executing operations: {str(e)}\n\nOperations attempted:\n{operations_clean}"
    except KeyError as e:
        # Enhanced error message for missing columns
        available_dfs = {k: v for k, v in namespace.items() if isinstance(v, pd.DataFrame)}
        df_info = ""
        for df_name, df_obj in available_dfs.items():
            df_info += f"\n{df_name} columns: {df_obj.columns.tolist()}"
        return (
            f"Error executing operations: Column {str(e)} not found.\n"
            f"Available DataFrames and their columns:{df_info}\n\n"
            f"Operations attempted:\n{operations_clean}"
        )
    except Exception as e:
        # Enhanced error message with available DataFrames info
        available_dfs = {k: v for k, v in namespace.items() if isinstance(v, pd.DataFrame)}
        df_info = ""
        for df_name, df_obj in available_dfs.items():
            try:
                df_info += f"\n{df_name} columns: {df_obj.columns.tolist()}, shape: {df_obj.shape}"
            except:
                df_info += f"\n{df_name}: <error getting info>"
        return (
            f"Error executing operations: {str(e)}\n"
            f"Available DataFrames:{df_info}\n\n"
            f"Operations attempted:\n{operations_clean}"
        )

    result_dfs = {
        key: value for key, value in namespace.items()
        if isinstance(value, pd.DataFrame) and key != 'df'
    }

    if not result_dfs:
        return "No DataFrames were created. Please ensure your operations assign results to variables."

    # Select final output DataFrame
    selected_name = None
    selected_df = None

    if final_output and final_output in result_dfs:
        selected_name = final_output
        selected_df = result_dfs[final_output].copy()
    else:
        for candidate in (final_output, 'graph_df', 'df_selected', 'insights_df'):
            if candidate and candidate in result_dfs:
                selected_name = candidate
                selected_df = result_dfs[candidate].copy()
                break

    if selected_df is None:
        last_df_name, last_df = list(result_dfs.items())[-1]
        selected_name = final_output if final_output else last_df_name
        selected_df = last_df.copy()

    # Build output
    output = []
    output.append(f"\n{'='*70}")
    output.append(f"DataFrame: {selected_name}")
    output.append(f"Shape: {selected_df.shape[0]} rows × {selected_df.shape[1]} columns")
    output.append(f"\nData:")
    output.append(selected_df.to_string(index=False))
    
    numeric_cols = selected_df.select_dtypes(include=['number']).columns
    if len(numeric_cols) > 0:
        output.append(f"\nSummary Statistics:")
        output.append(selected_df[numeric_cols].describe().to_string())
    output.append("")

    # Add CSV block
    try:
        csv_text = selected_df.to_csv(index=False)
        output.append("CSV_DATA_START")
        output.append(csv_text)
        output.append("CSV_DATA_END")
    except Exception:
        pass

    return "\n".join(output)


