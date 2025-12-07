# FHIR Query Builder - Usage Guide

Complete guide for using the FHIR AI Query Builder tool.

## Table of Contents
1. [Installation](#installation)
2. [TUI (Terminal UI)](#tui-terminal-ui)
3. [CLI (Command Line)](#cli-command-line)
4. [Python API](#python-api)
5. [Examples](#examples)

---

## Installation

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv pip install -e ".[dev]"

# Or using pip
pip install -e ".[dev]"
```

### 2. Set Up API Key

Create a `.env` file in the project root:

```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

Get your API key from: https://console.anthropic.com/

---

## TUI (Terminal UI)

The TUI provides an interactive, step-by-step interface for building FHIR queries.

### Launch TUI

```bash
# Option 1: Using the entry point script
python fhir_query_builder.py

# Option 2: Using the installed command (after pip install -e .)
fhir-query-builder

# Option 3: Using Python module
python -m src.fhir_tui
```

### TUI Workflow

1. **Step 1: FHIR Server Configuration**
   - Enter FHIR server base URL
   - Default: `https://hapi.fhir.org/baseR4`
   - Click "Connect to Server"
   - Wait for metadata to load

2. **Step 2: Enter Your Query**
   - Type natural language query
   - Examples:
     - "Find all female patients born after 1990"
     - "Get blood pressure observations"
     - "Patients with diabetes in California"
   - Click "Select Resource Types"

3. **Step 3: Select Resource Type**
   - View AI-selected resource types
   - Each type shows:
     - Resource type name
     - Confidence score (0.0-1.0)
     - Reasoning for selection
   - First type is automatically selected
   - Click "Build Query"

4. **Step 4: Generated FHIR Query**
   - View the complete query
   - Shows:
     - Resource type
     - Query string
     - Full URL
   - Click "Copy to Clipboard" (requires pyperclip)

### Keyboard Shortcuts

- `q` - Quit application
- `r` - Reset form to start over
- `Tab` - Navigate between fields
- `Enter` - Activate buttons

---

## CLI (Command Line)

The CLI allows you to generate queries from the command line without the interactive UI.

### Basic Usage

```bash
# Using installed command
fhir-cli --query "Find female patients born after 1990"

# Using Python module
python -m src.cli --query "Find female patients born after 1990"
```

### CLI Options

```bash
fhir-cli [OPTIONS]

Options:
  -s, --server URL      FHIR server URL (default: https://hapi.fhir.org/baseR4)
  -q, --query TEXT      Natural language query
  -t, --type TYPE       Specific resource type (skips AI selection)
  -l, --list-types      List all available resource types
  -i, --interactive     Launch TUI instead of CLI
  -h, --help           Show help message
```

### CLI Examples

**1. Simple query with type selection:**
```bash
fhir-cli --query "Find all patients named Smith"
```

Output:
```
Connecting to FHIR server: https://hapi.fhir.org/baseR4
✓ Connected! Found 146 resource types

Analyzing query: 'Find all patients named Smith'

Selected 1 matching type(s):
  1. Patient (confidence: 0.95)
     The query explicitly asks for 'patients' which directly maps to...

Using: Patient

Building FHIR query for Patient...
✓ Success!

Resource Type: Patient
Query String:  family=Smith

Full URL:
https://hapi.fhir.org/baseR4/Patient?family=Smith
```

**2. Query with specific server:**
```bash
fhir-cli --server "https://r4.smarthealthit.org" \
         --query "Female patients in California"
```

**3. Query with specified type (no AI selection):**
```bash
fhir-cli --type Patient \
         --query "Born after 1990 in New York"
```

**4. List available resource types:**
```bash
fhir-cli --list-types
```

**5. Launch TUI from CLI:**
```bash
fhir-cli --interactive
```

---

## Python API

Use the agents programmatically in your Python code.

### Basic Usage

```python
from agents import (
    fetch_searchable_resources,
    SelectTypesAgent,
    CreateQueryAgent,
    COMMON_SEARCH_PARAMS
)

# 1. Connect to FHIR server
metadata = fetch_searchable_resources("https://hapi.fhir.org/baseR4")

# 2. Select resource type
select_agent = SelectTypesAgent(metadata)
types = select_agent.select_types("Find female patients born after 1990")

# 3. Build query
query_agent = CreateQueryAgent(
    target_type=types[0].selected_type,
    metadata=metadata,
    common_search_params=COMMON_SEARCH_PARAMS
)
result = query_agent.agent.run_sync("Find female patients born after 1990")

# 4. Use the query
print(f"Query: {result.output.query_string}")
```

### Advanced Usage

**Handle multiple type suggestions:**
```python
types = select_agent.select_types("Get medication data")

for selected_type in types:
    print(f"{selected_type.selected_type}: {selected_type.confidence:.2f}")
    print(f"  Reasoning: {selected_type.reasoning}\n")
```

**Error handling:**
```python
from agents import SelectTypeError, CreateQueryError

# Type selection errors
results = select_agent.select_types("Find XYZ records")
if isinstance(results, SelectTypeError):
    print(f"Error: {results.error}")
    print(f"Reason: {results.reasoning}")

# Query building errors
result = query_agent.agent.run_sync("impossible query")
if isinstance(result.output, CreateQueryError):
    print(f"Error: {result.output.error}")
    print(f"Suggestion: {result.output.suggestion}")
```

**Using different FHIR servers:**
```python
# SMART Health IT
metadata_smart = fetch_searchable_resources("https://r4.smarthealthit.org")

# HAPI FHIR
metadata_hapi = fetch_searchable_resources("https://hapi.fhir.org/baseR4")

# Your custom server
metadata_custom = fetch_searchable_resources("https://your-server.com/fhir")
```

---

## Examples

### Example 1: Patient Search

**Query:** "Find active female patients in California born between 1980-1990"

**Steps:**
1. Launch TUI or use CLI
2. Enter query
3. System selects "Patient" resource type
4. Generates query:

```
gender=female&active=true&address-state=California&birthdate=ge1980&birthdate=le1990
```

**Full URL:**
```
https://hapi.fhir.org/baseR4/Patient?gender=female&active=true&address-state=California&birthdate=ge1980&birthdate=le1990
```

### Example 2: Observation Search with Chaining

**Query:** "Blood pressure readings for patients named Smith"

**Steps:**
1. System selects "Observation" type
2. Generates query with chaining:

```
code=http://loinc.org|85354-9&patient.name=Smith
```

**Full URL:**
```
https://hapi.fhir.org/baseR4/Observation?code=http://loinc.org|85354-9&patient.name=Smith
```

### Example 3: Medication Request

**Query:** "Get 10 most recent medication prescriptions"

**Steps:**
1. System may suggest: MedicationRequest, MedicationStatement
2. Select MedicationRequest
3. Generates:

```
_sort=-_lastUpdated&_count=10
```

### Example 4: Using Python API in a Script

```python
#!/usr/bin/env python3
"""
Script to generate FHIR queries and save to file
"""

from agents import *

def generate_queries(queries: list[str], output_file: str):
    # Connect once
    metadata = fetch_searchable_resources()
    select_agent = SelectTypesAgent(metadata)

    results = []

    for query_text in queries:
        # Select type
        types = select_agent.select_types(query_text)
        if isinstance(types, SelectTypeError):
            results.append(f"ERROR: {query_text}\n  {types.error}\n")
            continue

        # Build query for first type
        resource_type = types[0].selected_type
        query_agent = CreateQueryAgent(resource_type, metadata, COMMON_SEARCH_PARAMS)
        result = query_agent.agent.run_sync(query_text)

        if isinstance(result.output, CreateQueryError):
            results.append(f"ERROR: {query_text}\n  {result.output.error}\n")
            continue

        # Save result
        full_url = f"{metadata.server_url}/{resource_type}?{result.output.query_string}"
        results.append(f"{query_text}\n  {full_url}\n")

    # Write to file
    with open(output_file, 'w') as f:
        f.write('\n'.join(results))

    print(f"✓ Generated {len(results)} queries → {output_file}")

# Usage
queries = [
    "Find female patients born after 1990",
    "Blood pressure observations",
    "Diabetes diagnoses",
]

generate_queries(queries, "fhir_queries.txt")
```

---

## Tips & Best Practices

### 1. Query Writing

**Good queries:**
- "Find female patients born after 1990 in California"
- "Blood pressure readings for patient Smith"
- "Active medication requests from last 30 days"

**Vague queries (may produce errors):**
- "Get data" → Too vague, no resource type clear
- "Find stuff" → No clear intent
- "XYZ records" → Non-existent resource type

### 2. Performance

- Connect to server once, reuse metadata
- Cache SelectTypesAgent and CreateQueryAgent instances
- Use specific resource types when possible (skip AI selection)

### 3. Error Handling

Always check for errors:
```python
if isinstance(result, SelectTypeError):
    # Handle type selection error

if isinstance(result.output, CreateQueryError):
    # Handle query building error
```

### 4. Server Compatibility

Different FHIR servers support different:
- Resource types
- Search parameters
- FHIR versions

Always fetch fresh metadata when switching servers.

---

## Troubleshooting

**Problem:** "No module named 'agents'"
**Solution:** Run from project root, install dependencies

**Problem:** "ANTHROPIC_API_KEY not found"
**Solution:** Create `.env` file with API key

**Problem:** "Connection failed"
**Solution:** Check server URL, internet connection

**Problem:** Type selection returns error
**Solution:** Try more specific query, check if type exists on server

**Problem:** Query building fails
**Solution:** Check if requested parameters are available for that resource type

---

## Additional Resources

- [FHIR R4 Specification](https://www.hl7.org/fhir/)
- [FHIR Search](https://www.hl7.org/fhir/search.html)
- [Textual Documentation](https://textual.textualize.io/)
- [Pydantic AI](https://ai.pydantic.dev/)
