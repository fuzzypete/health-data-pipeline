# Decision: Labs Biomarker Standardization

**Date:** 2024-10-01  
**Status:** Implemented  
**Impact:** Critical (enables longitudinal biomarker tracking)

## Context

Laboratory results come from multiple providers (Quest, LabCorp, other) with inconsistent naming conventions, reference ranges, and units. Need standardized representation for accurate longitudinal tracking and correlation analysis.

## Problem

### 1. Name Variation
Same biomarker called different things:

| Quest | LabCorp | Other Labs |
|-------|---------|------------|
| "Testosterone, Total" | "Total Testosterone" | "Testosterone Total" |
| "Cholesterol, Total" | "Total Cholesterol" | "Cholesterol" |
| "Hemoglobin A1c" | "HbA1c" | "Glycosylated Hemoglobin" |

**Impact:** Cannot track biomarker over time if name changes between tests.

### 2. Reference Range Variation
Same biomarker, different "normal" ranges:

| Lab | Test | Reference Range | Method |
|-----|------|----------------|---------|
| Quest | Total Testosterone | 264-916 ng/dL | LC-MS |
| LabCorp | Total Testosterone | 250-1100 ng/dL | Immunoassay |
| Quest | Ferritin | 30-400 ng/mL | Immunoassay |
| LabCorp | Ferritin | 24-336 ng/mL | Chemiluminescence |

**Impact:**
- "Normal" at one lab may be "high" at another
- Cannot reliably flag concerning values
- Optimization targets unclear

### 3. Unit Inconsistency
Some labs report in different units:

| Biomarker | Unit 1 | Unit 2 | Conversion |
|-----------|--------|--------|------------|
| Glucose | mg/dL | mmol/L | ×18.02 |
| Vitamin D | ng/mL | nmol/L | ×2.5 |
| Testosterone | ng/dL | ng/mL | ×10 |

**Impact:** Must convert for comparison, easy to make errors.

### 4. Optimal vs Reference Ranges
Lab "normal" ranges are often:
- Defined by 95th percentile of *tested population* (not healthy population)
- Not optimized for longevity/performance
- Too wide for health optimization

**Example:**
- Ferritin reference range (Quest): 30-400 ng/mL
- Optimal range (longevity literature): 50-150 ng/mL
- A result of 35 ng/mL is "normal" but suboptimal

## Options Considered

### Option 1: Store Raw Lab Names
Keep exact lab naming as-is.

**Pros:**
- No transformation needed
- Audit trail preserved

**Cons:**
- **Cannot track longitudinally** - name changes break history
- Must manually map for each query
- Queries become complex (CASE statements for every biomarker)

### Option 2: Manual Mapping Per Query
Store raw names, map in queries.

```sql
SELECT 
    CASE 
        WHEN biomarker_name IN ('Testosterone, Total', 'Total Testosterone') 
        THEN 'Total Testosterone'
        ...
    END as standardized_name,
    result_value
FROM labs_results
```

**Pros:**
- Flexible - can change mapping without reprocessing data

**Cons:**
- **Error-prone** - must remember mapping in every query
- Verbose queries
- Mapping logic scattered across codebase

### Option 3: Canonical Mapping Table (CHOSEN)
Maintain reference table of canonical names + aliases.

**Pros:**
- **Single source of truth** for biomarker identity
- Clean queries - just use canonical name
- Easy to add new lab aliases
- Audit trail: Store both canonical and original name

**Cons:**
- Requires building and maintaining mapping table
- Need to update when encountering new lab variations

## Decision

Implement **canonical mapping table** with alias resolution.

### Components

**1. Canonical Biomarker Names**
Define standardized naming convention:
- Lowercase with underscores: `testosterone_total`
- Consistent across all sources
- Based on common medical terminology

**2. Alias Mapping**
Map lab-specific names to canonical:
```python
aliases = {
    'testosterone_total': [
        'Testosterone, Total',
        'Total Testosterone',
        'Testosterone Total',
        'Testosterone (Total)'
    ],
    'ferritin': [
        'Ferritin',
        'Ferritin, Serum',
        'Serum Ferritin'
    ]
}
```

**3. Optimal Ranges**
Store longevity-focused targets separate from lab reference ranges:
```python
optimal_ranges = {
    'testosterone_total': {
        'unit': 'ng/dL',
        'optimal_low': 550,
        'optimal_high': 850
    },
    'ferritin': {
        'unit': 'ng/mL',
        'optimal_low': 50,
        'optimal_high': 150
    }
}
```

## Implementation

### Schema Design

```sql
-- Main results table
CREATE TABLE labs_results (
    result_id UUID PRIMARY KEY,
    test_date DATE,
    lab_company STRING,
    biomarker_name STRING,  -- Canonical name
    original_name STRING,   -- Lab-specific name (audit trail)
    result_value FLOAT,
    result_unit STRING,
    
    -- Lab reference ranges
    reference_range_low FLOAT,
    reference_range_high FLOAT,
    
    -- Optimal ranges
    optimal_range_low FLOAT,
    optimal_range_high FLOAT,
    
    flag STRING,  -- normal, high, low, critical
    test_method STRING,
    fasting_status BOOLEAN
);

-- Mapping table
CREATE TABLE biomarker_mappings (
    canonical_name STRING PRIMARY KEY,
    aliases ARRAY<STRING>,
    category STRING,  -- lipid, hormone, mineral, etc.
    optimal_range_low FLOAT,
    optimal_range_high FLOAT,
    optimal_range_unit STRING,
    clinical_significance TEXT
);
```

### Ingestion Logic

```python
def standardize_biomarker(lab_name: str) -> dict:
    """
    Map lab-specific name to canonical name.
    Return canonical name + optimal ranges.
    """
    # Load mapping table
    mappings = load_biomarker_mappings()
    
    # Search for match in aliases
    for canonical, mapping in mappings.items():
        if lab_name in mapping['aliases']:
            return {
                'canonical_name': canonical,
                'original_name': lab_name,
                'optimal_range_low': mapping['optimal_range_low'],
                'optimal_range_high': mapping['optimal_range_high'],
                'category': mapping['category']
            }
    
    # Not found - flag for manual review
    log_unmapped_biomarker(lab_name)
    return {
        'canonical_name': None,
        'original_name': lab_name,
        'optimal_range_low': None,
        'optimal_range_high': None
    }

# During ingestion
for row in lab_results:
    standard = standardize_biomarker(row['biomarker_name'])
    row['biomarker_name'] = standard['canonical_name']
    row['original_name'] = standard['original_name']
    row['optimal_range_low'] = standard['optimal_range_low']
    row['optimal_range_high'] = standard['optimal_range_high']
```

### Flagging Logic

```python
def calculate_flag(value, ref_low, ref_high, opt_low, opt_high):
    """
    Determine if result is:
    - critical: Outside reference range
    - suboptimal: In reference but outside optimal
    - optimal: In optimal range
    """
    if value < ref_low or value > ref_high:
        return 'critical'
    elif value < opt_low or value > opt_high:
        return 'suboptimal'
    else:
        return 'optimal'
```

## Biomarker Categories

Group biomarkers for easier analysis:

```python
categories = {
    'lipid': [
        'cholesterol_total',
        'cholesterol_ldl',
        'cholesterol_hdl',
        'triglycerides',
        'apob'
    ],
    'hormone': [
        'testosterone_total',
        'testosterone_free',
        'estradiol',
        'shbg',
        'prolactin'
    ],
    'metabolic': [
        'glucose_fasting',
        'hba1c',
        'insulin_fasting',
        'uric_acid'
    ],
    'mineral': [
        'iron_serum',
        'ferritin',
        'tibc',
        'iron_saturation',
        'magnesium',
        'zinc'
    ],
    'inflammatory': [
        'hscrp',
        'homocysteine'
    ],
    'liver': [
        'alt',
        'ast',
        'ggt',
        'alp',
        'bilirubin_total'
    ],
    'kidney': [
        'creatinine',
        'bun',
        'egfr'
    ],
    'blood': [
        'hemoglobin',
        'hematocrit',
        'rbc',
        'wbc',
        'platelets',
        'mcv',
        'mch',
        'mchc'
    ]
}
```

## Optimal Range Sources

Optimal ranges derived from:
1. **Longevity literature:** Studies on centenarians, healthspan optimization
2. **Performance research:** Athletic optimization studies
3. **Clinical guidelines:** Evidence-based recommendations (when available)
4. **N=1 experimentation:** Personal response patterns

**Example: Ferritin**
- Lab reference: 30-400 ng/mL (Quest)
- Optimal range: 50-150 ng/mL
- Rationale:
  - < 50: Increased fatigue, reduced endurance performance
  - > 150: Increased oxidative stress, inflammation
  - Source: Multiple studies on iron status in athletes

**Note:** Optimal ranges are guidelines, not absolutes. Individual response varies.

## Query Patterns

### Longitudinal Tracking
```sql
-- Track testosterone over time
SELECT 
    test_date,
    result_value,
    optimal_range_low,
    optimal_range_high,
    CASE 
        WHEN result_value >= optimal_range_low 
         AND result_value <= optimal_range_high 
        THEN 'optimal'
        ELSE 'suboptimal'
    END as status
FROM labs_results
WHERE biomarker_name = 'testosterone_total'
ORDER BY test_date;
```

### Category Analysis
```sql
-- All lipid panel results on specific date
SELECT 
    biomarker_name,
    result_value,
    result_unit,
    flag
FROM labs_results
WHERE test_date = '2024-11-01'
  AND biomarker_name IN (
      'cholesterol_total', 'cholesterol_ldl', 
      'cholesterol_hdl', 'triglycerides', 'apob'
  )
ORDER BY biomarker_name;
```

### Protocol Effectiveness
```sql
-- Ferritin change during iron protocol
WITH protocol AS (
    SELECT start_date, end_date
    FROM protocols_phases
    WHERE phase_name = 'Iron Repletion Protocol'
)
SELECT 
    l.test_date,
    l.result_value as ferritin,
    l.result_value - LAG(l.result_value) OVER (ORDER BY l.test_date) as delta,
    CASE 
        WHEN l.result_value >= l.optimal_range_low THEN 'on target'
        ELSE 'below target'
    END as status
FROM labs_results l
JOIN protocol p ON l.test_date BETWEEN p.start_date AND p.end_date
WHERE l.biomarker_name = 'ferritin'
ORDER BY l.test_date;
```

## Handling New Biomarkers

When encountering unknown biomarker name:

1. **Log for review:**
   ```python
   logger.warning(f"Unmapped biomarker: {lab_name} from {lab_company}")
   ```

2. **Store with `canonical_name = NULL`:**
   - Preserves data
   - Flags for manual mapping

3. **Update mapping table:**
   ```python
   # Add to biomarker_mappings
   new_mapping = {
       'canonical_name': 'vitamin_b12',
       'aliases': ['Vitamin B12', 'Cobalamin', 'B12'],
       'category': 'vitamin',
       'optimal_range_low': 500,
       'optimal_range_high': 1500,
       'optimal_range_unit': 'pg/mL'
   }
   ```

4. **Re-process affected records:**
   ```python
   # Update historical records with new mapping
   UPDATE labs_results
   SET biomarker_name = 'vitamin_b12'
   WHERE original_name IN ('Vitamin B12', 'Cobalamin')
     AND biomarker_name IS NULL;
   ```

## Results

**Before Standardization:**
- Could not track testosterone over time (5 different names across labs)
- Queries required complex CASE statements
- Missed suboptimal results flagged as "normal"

**After Standardization:**
- Clean longitudinal tracking across all labs
- Simple queries using canonical names
- Both reference and optimal range comparisons
- Automatic flagging of suboptimal results

### Biomarker Coverage

Currently mapped biomarkers: ~50
- Lipid panel: 7 biomarkers
- Hormone panel: 8 biomarkers
- Metabolic: 6 biomarkers
- Minerals: 12 biomarkers
- Blood: 15 biomarkers
- Other: 12 biomarkers

## Trade-offs Accepted

1. **Manual mapping required:**
   - Cannot auto-detect all aliases
   - Must update table when encountering new labs
   - Acceptable: One-time effort per new alias

2. **Optimal ranges are opinionated:**
   - Based on literature + N=1 experience
   - May not apply universally
   - Acceptable: Better to have targets than wing it

3. **Unit conversion not automated:**
   - Labs usually consistent within company
   - Manual conversion if needed
   - Acceptable: Rare edge case, can add later if needed

## Lessons Learned

1. **Build mapping table early:**
   - Harder to retrofit after accumulating data
   - Worth the upfront investment

2. **Preserve original names:**
   - Audit trail essential for debugging
   - Can verify mapping is correct

3. **Separate reference from optimal:**
   - "Normal" ≠ optimal for performance/longevity
   - Both perspectives valuable

4. **Category grouping is useful:**
   - Easier to analyze related biomarkers together
   - Natural way to organize results

## Testing Strategy

```python
def test_biomarker_mapping():
    """Aliases resolve to canonical name"""
    assert standardize('Testosterone, Total') == 'testosterone_total'
    assert standardize('Total Testosterone') == 'testosterone_total'
    
def test_unmapped_biomarker():
    """Unknown biomarkers logged and preserved"""
    result = standardize('Mystery Biomarker 9000')
    assert result['canonical_name'] is None
    assert result['original_name'] == 'Mystery Biomarker 9000'
    
def test_optimal_range_flagging():
    """Suboptimal results detected"""
    flag = calculate_flag(
        value=35,
        ref_low=30, ref_high=400,
        opt_low=50, opt_high=150
    )
    assert flag == 'suboptimal'  # In reference but below optimal
```

---

**Related:**
- [DataSources.md](../DataSources.md) - Labs ingestion process
- [Schema.md](../Schema.md) - Labs table definitions
- [archive/HealthDataPipelineDesign_v2.3.md](../archive/HealthDataPipelineDesign_v2.3.md) - Detailed implementation
