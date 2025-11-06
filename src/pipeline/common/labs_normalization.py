"""
Labs data normalization utilities.

Handles:
- Extracting units from column names: "Ferritin (ng/mL)" → "Ferritin", "ng/mL"
- Parsing special values: "<10", ">1500" 
- Adding flags: "L" (low), "H" (high), "N" (normal)
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

import pandas as pd


def parse_column_name(col_name: str) -> Tuple[str, Optional[str]]:
    """
    Extract marker name and unit from column name.
    
    Examples:
        "Ferritin (ng/mL)" → ("Ferritin", "ng/mL")
        "Hemoglobin A1c (%)" → ("Hemoglobin A1c", "%")
        "Date" → ("Date", None)
    
    Args:
        col_name: Column name from Excel
        
    Returns:
        (marker_name, unit) tuple
    """
    # Pattern: "Marker Name (unit)"
    match = re.match(r'^(.+?)\s*\((.+?)\)$', col_name)
    if match:
        marker = match.group(1).strip()
        unit = match.group(2).strip()
        return marker, unit
    
    return col_name.strip(), None


def parse_lab_value(raw_value: any) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Parse lab value handling special cases.
    
    Examples:
        75 → (75.0, None, None)
        "<10" → (10.0, "<10", "L")
        ">1500" → (1500.0, ">1500", "H")
        "Negative" → (None, "Negative", None)
    
    Args:
        raw_value: Value from Excel cell
        
    Returns:
        (numeric_value, text_value, flag) tuple
        flag: "L" (below detection), "H" (above detection), None (normal/parseable)
    """
    if pd.isna(raw_value):
        return None, None, None
    
    val_str = str(raw_value).strip()
    
    # Handle <value (below detection limit)
    if val_str.startswith('<'):
        try:
            num = float(val_str[1:])
            return num, val_str, 'L'
        except ValueError:
            return None, val_str, None
    
    # Handle >value (above detection limit)
    if val_str.startswith('>'):
        try:
            num = float(val_str[1:])
            return num, val_str, 'H'
        except ValueError:
            return None, val_str, None
    
    # Handle numeric
    try:
        return float(val_str), None, None
    except ValueError:
        # Non-numeric text (e.g., "Negative", "Not Detected")
        return None, val_str, None


def calculate_flag(
    value: Optional[float],
    ref_low: Optional[float],
    ref_high: Optional[float],
    existing_flag: Optional[str] = None
) -> Optional[str]:
    """
    Calculate flag based on value and reference range.
    
    Args:
        value: Numeric test result
        ref_low: Lower bound of normal range
        ref_high: Upper bound of normal range
        existing_flag: Flag from parse_lab_value (for <,> symbols)
        
    Returns:
        "L" (low), "H" (high), "N" (normal), or None
    """
    # If we already have a flag from parsing (e.g., "<10"), keep it
    if existing_flag:
        return existing_flag
    
    if value is None:
        return None
    
    # Check against reference ranges
    if ref_low is not None and value < ref_low:
        return 'L'
    if ref_high is not None and value > ref_high:
        return 'H'
    
    # Within normal range
    if ref_low is not None or ref_high is not None:
        return 'N'
    
    return None


# Reference ranges for common tests
# Add more as needed
REFERENCE_RANGES = {
    'Ferritin': {'unit': 'ng/mL', 'low': 30.0, 'high': 400.0},
    'Glucose': {'unit': 'mg/dL', 'low': 70.0, 'high': 100.0},
    'Hemoglobin A1c': {'unit': '%', 'low': None, 'high': 5.7},
    'Insulin': {'unit': 'uIU/mL', 'low': 2.0, 'high': 25.0},
    'hs CRP': {'unit': 'mg/L', 'low': None, 'high': 3.0},
    'Vitamin D': {'unit': 'ng/mL', 'low': 30.0, 'high': 100.0},
    
    # CBC
    'WBC': {'unit': 'x10E3/uL', 'low': 4.0, 'high': 11.0},
    'RBC': {'unit': 'x10E6/uL', 'low': 4.5, 'high': 6.0},
    'Hemoglobin': {'unit': 'g/dL', 'low': 13.5, 'high': 17.5},
    'Hematocrit': {'unit': '%', 'low': 38.0, 'high': 50.0},
    'MCV': {'unit': 'fL', 'low': 80.0, 'high': 100.0},
    'MCH': {'unit': 'pg', 'low': 27.0, 'high': 33.0},
    'MCHC': {'unit': 'g/dL', 'low': 32.0, 'high': 36.0},
    'RDW': {'unit': '%', 'low': 11.5, 'high': 14.5},
    'Platelets': {'unit': 'x10E3/uL', 'low': 150.0, 'high': 400.0},
    
    # Metabolic panel
    'Sodium': {'unit': 'mmol/L', 'low': 136.0, 'high': 145.0},
    'Potassium': {'unit': 'mmol/L', 'low': 3.5, 'high': 5.0},
    'Chloride': {'unit': 'mmol/L', 'low': 98.0, 'high': 107.0},
    'CO2': {'unit': 'mmol/L', 'low': 23.0, 'high': 29.0},
    'BUN': {'unit': 'mg/dL', 'low': 7.0, 'high': 20.0},
    'Creatinine': {'unit': 'mg/dL', 'low': 0.7, 'high': 1.3},
    'eGFR': {'unit': 'mL/min/1.73m2', 'low': 90.0, 'high': None},
    'Calcium': {'unit': 'mg/dL', 'low': 8.5, 'high': 10.5},
    
    # Liver
    'ALT': {'unit': 'U/L', 'low': None, 'high': 40.0},
    'AST': {'unit': 'U/L', 'low': None, 'high': 40.0},
    'Alk Phos': {'unit': 'U/L', 'low': 40.0, 'high': 150.0},
    'Bilirubin, Total': {'unit': 'mg/dL', 'low': None, 'high': 1.2},
    
    # Lipids
    'Cholesterol, Total': {'unit': 'mg/dL', 'low': None, 'high': 200.0},
    'Triglycerides': {'unit': 'mg/dL', 'low': None, 'high': 150.0},
    'HDL': {'unit': 'mg/dL', 'low': 40.0, 'high': None},
    'LDL (calc)': {'unit': 'mg/dL', 'low': None, 'high': 100.0},
    'ApoB': {'unit': 'mg/dL', 'low': None, 'high': 100.0},
    'Lp(a)': {'unit': 'nmol/L', 'low': None, 'high': 75.0},
    'LDL-P': {'unit': 'nmol/L', 'low': None, 'high': 1000.0},
    
    # Hormones
    'Testosterone, Total': {'unit': 'ng/dL', 'low': 264.0, 'high': 916.0},
    'Testosterone, Free': {'unit': 'pg/mL', 'low': 5.0, 'high': 30.0},
    'Estradiol': {'unit': 'pg/mL', 'low': 10.0, 'high': 40.0},
    'SHBG': {'unit': 'nmol/L', 'low': 10.0, 'high': 57.0},
    'DHEA-S': {'unit': 'mcg/dL', 'low': 80.0, 'high': 560.0},
    'DHT': {'unit': 'ng/dL', 'low': 30.0, 'high': 85.0},
    'IGF-1': {'unit': 'ng/mL', 'low': 101.0, 'high': 267.0},
    'LH': {'unit': 'mIU/mL', 'low': 1.7, 'high': 8.6},
    'FSH': {'unit': 'mIU/mL', 'low': 1.5, 'high': 12.4},
    'Prolactin': {'unit': 'ng/mL', 'low': 4.0, 'high': 15.2},
    'PSA': {'unit': 'ng/mL', 'low': None, 'high': 4.0},
}


def get_reference_range(marker: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Get reference range for a marker.
    
    Args:
        marker: Test marker name
        
    Returns:
        (ref_low, ref_high) tuple
    """
    ref_data = REFERENCE_RANGES.get(marker, {})
    return ref_data.get('low'), ref_data.get('high')
