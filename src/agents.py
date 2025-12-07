"""
FHIR AI Query Builder Agents

This module provides AI agents for building FHIR queries:
- SelectTypesAgent: Selects appropriate FHIR resource types from natural language
- CreateQueryAgent: Builds valid FHIR search queries for a given resource type

It also includes utilities for fetching FHIR server metadata and search parameters.
"""

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
import requests
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated


# ============================================================================
# Pydantic Models for FHIR Metadata
# ============================================================================

class SearchParameter(BaseModel):
    """FHIR search parameter definition"""
    name: str
    type: str | None  # Can sometimes be None if special type
    documentation: str | None = None

    def __str__(self):
        return f"{self.name} ({self.type}): {self.documentation}"


class ResourceMetadata(BaseModel):
    """Metadata for a single FHIR resource type"""
    type: str
    profile: str | None = None
    interactions: list[str]  # ['read', 'search-type', 'create', etc.]
    search_params: list[SearchParameter]
    include_values: list[str]
    revinclude_values: list[str]


class FHIRMetadata(BaseModel):
    """Complete FHIR server metadata response"""
    searchable_types: list[str] = Field(
        description="List of resource types that support search-type interaction"
    )
    resource_metadata: dict[str, ResourceMetadata] = Field(
        description="Full metadata for each resource type, keyed by type name"
    )
    fhir_version: str | None = None
    server_url: str


# ============================================================================
# Metadata Query Function
# ============================================================================

def fetch_searchable_resources(base_url: str = "https://r4.smarthealthit.org") -> FHIRMetadata:
    """
    Fetch searchable resource types from FHIR server metadata.

    Based on reference code that queries /metadata endpoint and filters
    resources with 'search-type' interaction capability.

    Args:
        base_url: FHIR server base URL (default: SMART Health IT R4 server)

    Returns:
        FHIRMetadata: Pydantic model containing searchable types and full resource metadata

    Raises:
        requests.RequestException: If network request fails
        ValueError: If response is invalid or missing required fields
    """
    # Query metadata endpoint
    metadata_url = f"{base_url}/metadata"

    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        capability_statement = response.json()
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch metadata from {metadata_url}: {e}")

    # Validate response structure
    if not capability_statement.get('rest') or len(capability_statement['rest']) == 0:
        raise ValueError("Invalid CapabilityStatement: missing 'rest' array")

    if not capability_statement['rest'][0].get('resource'):
        raise ValueError("Invalid CapabilityStatement: missing 'resource' array in rest[0]")

    # Extract searchable resources (matching reference code logic)
    searchable_types: list[str] = []
    resource_metadata: dict[str, ResourceMetadata] = {}

    server_capability_metadata = next(
        (x for x in capability_statement['rest'] if x['mode'] == "server"),
        None  # default value if not found
    )
    if server_capability_metadata is None:
        raise ValueError("FHIR server does not expose capability information")

    for resource in server_capability_metadata['resource']:
        resource_type = resource.get('type')
        if not resource_type:
            continue

        # Check if resource supports search-type interaction (reference line 74-79)
        interactions = resource.get('interaction', [])
        interaction_codes = [interaction.get('code') for interaction in interactions]

        if 'search-type' in interaction_codes:
            searchable_types.append(resource_type)

            # Parse search parameters and sort alphabetically (reference line 81-90)
            search_params: list[SearchParameter] = []
            for param in resource.get('searchParam', []):
                search_params.append(SearchParameter(
                    name=param.get('name'),
                    type=param.get('type'),
                    documentation=param.get('documentation')
                ))

            # Sort by name (matching reference code)
            search_params.sort(key=lambda p: p.name)

            # Create ResourceMetadata object
            resource_metadata[resource_type] = ResourceMetadata(
                type=resource_type,
                profile=resource.get('profile'),
                interactions=interaction_codes,
                search_params=search_params,
                include_values=resource.get('searchInclude', []),
                revinclude_values=resource.get('searchRevInclude', [])
            )

    return FHIRMetadata(
        searchable_types=searchable_types,
        resource_metadata=resource_metadata,
        fhir_version=capability_statement.get('fhirVersion'),
        server_url=base_url
    )


# ============================================================================
# Utility Functions
# ============================================================================

def get_search_parameters(
    resource_type: str,
    metadata: FHIRMetadata
) -> list[SearchParameter]:
    """
    Get available search parameters for a specific FHIR resource type.

    Args:
        resource_type: The FHIR resource type name (e.g., 'Patient', 'Observation')
        metadata: FHIRMetadata object containing cached resource metadata

    Returns:
        List of SearchParameter objects for the given resource type

    Raises:
        ValueError: If resource_type is not found in metadata
    """
    if resource_type not in metadata.resource_metadata:
        available_types = ', '.join(sorted(metadata.searchable_types)[:10])
        raise ValueError(
            f"Resource type '{resource_type}' not found in metadata. "
            f"Available types include: {available_types}..."
        )

    return metadata.resource_metadata[resource_type].search_params


# ============================================================================
# Select Types Agent Models
# ============================================================================

class SelectedResourceType(BaseModel):
    """A single selected FHIR resource type with confidence and reasoning"""
    selected_type: str = Field(
        description="The selected resource type name"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0) for this selection"
    )
    reasoning: str = Field(
        description="Explanation of why this type was selected"
    )


class SelectTypeError(BaseModel):
    """Error result when type selection fails"""
    error: str = Field(
        description="Error message describing what went wrong"
    )
    reasoning: str = Field(
        description="Explanation of why the selection failed"
    )


# ============================================================================
# Select Types Agent Class
# ============================================================================

class SelectTypesAgent:
    """Agent for selecting FHIR resource types from natural language queries"""

    def __init__(self, metadata: FHIRMetadata):
        """
        Initialize the agent with FHIR server metadata.

        Args:
            metadata: FHIRMetadata object containing available searchable types
        """
        self.metadata = metadata
        self.model = AnthropicModel('claude-opus-4-5')

        # Create agent that returns a list of SelectedResourceType or SelectTypeError
        self.agent = Agent(
            model=self.model,
            output_type=list[SelectedResourceType] | SelectTypeError,
            system_prompt=self._build_system_prompt()
        )

    def select_types(self, query: str) -> list[SelectedResourceType] | SelectTypeError:
        """
        Analyze query and return selected resource types.

        Args:
            query: Natural language query from user

        Returns:
            List of SelectedResourceType (with individual confidence/reasoning)
            or SelectTypeError if selection fails
        """
        result = self.agent.run_sync(query)
        return result.output

    def _build_system_prompt(self) -> str:
        """Build dynamic system prompt with available types from metadata"""
        types_list = "\n".join(sorted(self.metadata.searchable_types))

        return f"""You are a FHIR resource type selector. Analyze user queries and select the appropriate FHIR resource type(s).

Available searchable resource types ({len(self.metadata.searchable_types)} total):
{types_list}

Your task:
1. Analyze the user's query to understand what data they want
2. Select the most appropriate resource type(s) from the available list above
3. Return a list of SelectedResourceType objects, each with:
   - selected_type: the resource type name
   - confidence: your confidence score for this specific type (0.0-1.0)
   - reasoning: why this specific type was selected
4. Order results by relevance (most relevant first)

Confidence scoring guidelines (per type):
- 0.9-1.0: Exact type name mentioned or very clear semantic match
- 0.7-0.9: Clear semantic match with good context
- 0.5-0.7: Reasonable match but some ambiguity
- 0.3-0.5: Multiple valid options, this is one possibility
- 0.0-0.3: Very uncertain, weak match

Common mappings:
- "patients", "patient demographics", "people" → Patient
- "vital signs", "blood pressure", "lab results", "observations" → Observation
- "medications", "prescriptions", "drugs" → Medication, MedicationRequest
- "encounters", "visits", "appointments" → Encounter
- "procedures", "surgeries", "operations" → Procedure
- "conditions", "diagnoses", "problems", "diseases" → Condition
- "allergies" → AllergyIntolerance
- "immunizations", "vaccinations" → Immunization

Error handling:
- If requested type doesn't exist in available list: return a SelectTypeError with error message and reasoning
- If type exists but query is ambiguous: return multiple SelectedResourceType objects, each with their own confidence
- If query is too vague: return most likely types with lower confidence scores

IMPORTANT:
- Only select types from the available list above
- Each SelectedResourceType in your list should have its own reasoning explaining why THAT specific type matches
- For ambiguous queries, return multiple types with individual confidence scores
- If NO valid types can be found, return a single SelectTypeError

Examples:
- "Find patients" → [SelectedResourceType(selected_type="Patient", confidence=0.95, reasoning="Direct match...")]
- "Get medication data" → [
    SelectedResourceType(selected_type="Medication", confidence=0.7, reasoning="Could be medication definitions..."),
    SelectedResourceType(selected_type="MedicationRequest", confidence=0.8, reasoning="Most likely prescription orders..."),
  ]
- "Find XYZ" → [SelectTypeError(error="Type 'XYZ' not found", reasoning="...")]"""


# ============================================================================
# Common Search Parameters
# ============================================================================

COMMON_SEARCH_PARAMS = [
    SearchParameter(
        name="_id",
        type="token",
        documentation="The logical id of the resource (e.g., _id=123)"
    ),
    SearchParameter(
        name="_lastUpdated",
        type="date",
        documentation="When the resource was last changed (e.g., _lastUpdated=gt2023-01-01)"
    ),
    SearchParameter(
        name="_tag",
        type="token",
        documentation="Tags applied to this resource in Resource.meta.tag"
    ),
    SearchParameter(
        name="_profile",
        type="reference",
        documentation="Profiles this resource claims to conform to in Resource.meta.profile"
    ),
    SearchParameter(
        name="_security",
        type="token",
        documentation="Security labels applied to this resource in Resource.meta.security"
    ),
    SearchParameter(
        name="_source",
        type="uri",
        documentation="Identifies the source system in Resource.meta.source"
    ),
    SearchParameter(
        name="_language",
        type="token",
        documentation="Language of the resource content"
    ),
    SearchParameter(
        name="_text",
        type="string",
        documentation="Search on the narrative text of the resource (special)"
    ),
    SearchParameter(
        name="_content",
        type="string",
        documentation="Search on the entire content of the resource (special)"
    ),
    SearchParameter(
        name="_list",
        type="special",
        documentation="Search resources referenced by a List resource"
    ),
    SearchParameter(
        name="_has",
        type="special",
        documentation="Reverse chaining - select resources based on properties of resources that refer to them. Examples: GET /Patient?_has:Observation:patient:code=1234-5 (Patients who have an Observation with code 1234-5), GET /Practitioner?_has:MedicationRequest:requester:_id=* (Practitioners who have authored any MedicationRequest)"
    ),
    SearchParameter(
        name="_type",
        type="special",
        documentation="Filter by resource type (used in system-level searches)"
    ),
    SearchParameter(
        name="_in",
        type="reference",
        documentation="Test membership in CareTeam, Group, or List"
    ),
    SearchParameter(
        name="_filter",
        type="special",
        documentation="Advanced filter expression (FHIRPath-like syntax)"
    ),
    SearchParameter(
        name="_query",
        type="special",
        documentation="Invoke a named/custom query operation"
    ),
    SearchParameter(
        name="_sort",
        type="string",
        documentation="Comma-separated list of sort rules. Prefix with - for descending order. Example: _sort=-date,status"
    ),
    SearchParameter(
        name="_count",
        type="number",
        documentation="Number of results per page. Example: _count=10"
    ),
    SearchParameter(
        name="_include",
        type="special",
        documentation="Include referenced resources in results. Syntax: _include=[Resource]:[searchParam] or [Resource]:[searchParam]:[targetType] or *. Example: _include=Observation:patient"
    ),
    SearchParameter(
        name="_revinclude",
        type="special",
        documentation="Include resources that reference the matches (reverse include). Syntax: _revinclude=[Resource]:[searchParam] or [Resource]:[searchParam]:[targetType] or *. Example: _revinclude=Provenance:target"
    ),
    SearchParameter(
        name="_summary",
        type="code",
        documentation="Return summary view: true, false, text, count, data"
    ),
    SearchParameter(
        name="_elements",
        type="string",
        documentation="Comma-separated list of elements to return. Example: _elements=identifier,name,birthDate"
    ),
    SearchParameter(
        name="_contained",
        type="code",
        documentation="How to handle contained resources: true, false, both"
    ),
    SearchParameter(
        name="_containedType",
        type="code",
        documentation="What to return when contained matches: container, contained"
    ),
    SearchParameter(
        name="_total",
        type="code",
        documentation="Request total count precision: none, estimate, accurate"
    ),
    SearchParameter(
        name="_maxresults",
        type="number",
        documentation="Maximum total results to return across all pages"
    ),
    SearchParameter(
        name="_score",
        type="boolean",
        documentation="Whether to include relevance scores (true/false)"
    ),
    SearchParameter(
        name="_graph",
        type="reference",
        documentation="Reference to a GraphDefinition for structured includes"
    )
]


# ============================================================================
# FHIR Search Syntax Summary
# ============================================================================

SYNTAX_SUMMARY_PROMPT = """# Syntax Considerations
## Chaining (Using . in Parameter Names)
Chaining allows searching on properties of referenced resources:

# Observations where the patient's name is "Smith"
GET /Observation?patient.name=Smith

# Observations where the patient has MRN 12345
GET /Observation?patient.identifier=http://hospital.org/mrn|12345

# With type disambiguation (when reference can be multiple types)
GET /Observation?subject:Patient.name=Smith

# Multiple levels of chaining
GET /DiagnosticReport?result.subject.name=Smith

## Combining Parameters (AND vs OR)
AND (intersection): Repeat the parameter or use different parameters
# Patient with given name "John" AND family name "Smith"
GET /Patient?given=John&family=Smith

OR (union): Use comma-separated values
# Patients with given name "John" OR "Jane"
GET /Patient?given=John,Jane

# How to Use Each Type:
1. Number
Searching on a simple numerical value in a resource. Values can include precision (e.g., 100 vs 100.00) and support exponential notation (e.g., 1e2). Supports prefixes: eq, ne, lt, le, gt, ge, sa, eb, ap.
Examples:
* [parameter]=100 — values equal to 100 (within precision)
* [parameter]=lt100 — values less than 100
* [parameter]=ge100 — values greater than or equal to 100
2. Date
A date parameter searches on date/time or period. The format is yyyy-mm-ddThh:mm:ss.ssss[Z|(+|-)hh:mm]. Date searches are intrinsically matches against periods. Supports the same prefixes as number parameters.
Examples:
* [parameter]=eq2013-01-14 — date is January 14, 2013
* [parameter]=ge2013-03-14 — date is on or after March 14, 2013
* [parameter]=lt2013-01-14T10:00 — before 10:00 on January 14, 2013
3. String
For a simple string search, a string parameter serves as input for a search against sequences of characters. This search is insensitive to casing and combining characters like accents. By default, a field matches if the value equals or starts with the supplied parameter value.
Modifiers:
* :contains — matches anywhere in the string
* :exact — case-sensitive exact match
Examples:
* given=eve — matches "Eve", "Evelyn"
* given:contains=eve — matches "Eve", "Evelyn", "Severine"
* given:exact=Eve — matches only "Eve" (case-sensitive)
4. Token
A token type provides a close to exact match search on a string of characters, potentially scoped by a URI. It is mostly used against code or identifier datatypes where the value may have a URI that scopes its meaning. Matches are literal and case sensitive unless the underlying semantics indicate otherwise.
Syntax:
* [parameter]=[code] — matches code regardless of system
* [parameter]=[system]|[code] — matches code within specific system
* [parameter]=|[code] — matches code with no system
* [parameter]=[system]| — matches any code in the system
Modifiers: :text, :not, :above, :below, :in, :not-in, :of-type
Examples:
* identifier=http://acme.org/patient|2345
* gender=male
* code:below=http://snomed.info/sct|235862008 — subsumption search
5. Reference
A reference parameter refers to references between resources. The interpretation is either: [id] (logical id), [type]/[id] (typed logical id), or [url] (absolute URL).
Modifiers: :[type], :identifier, :above, :below
Examples:
* subject=Patient/23
* subject:Patient=23
* subject:identifier=http://example.org/mrn|12345
6. Quantity
A quantity parameter searches on the Quantity datatype. The syntax is [prefix][number]|[system]|[code].
Examples:
* value-quantity=5.4|http://unitsofmeasure.org|mg — 5.4 mg (UCUM)
* value-quantity=5.4||mg — 5.4 mg (any system)
* value-quantity=le5.4|http://unitsofmeasure.org|mg — ≤5.4 mg
7. URI
The uri parameter refers to an element containing a URI. By default, matches are precise, case and accent sensitive, and the entire URI must match. The modifiers :above or :below can be used for partial matching.
Examples:
* url=http://acme.org/fhir/ValueSet/123
* url:below=http://acme.org/fhir — matches URLs starting with this path
8. Composite
Composite search parameters allow joining multiple elements into distinct single values with a $. This allows searches based on tuples of values, which is different from simple intersection.
Examples:
* code-value-quantity=http://loinc.org|2823-3$gt5.4|http://unitsofmeasure.org|mmol/L
* characteristic-value=gender$mixed
9. Special
A few parameters have the type 'special', indicating the way this parameter works is unique to the parameter and described with the parameter. The general modifiers and comparators do not apply except as stated in the description.

Common Prefixes (for number, date, quantity)
eq: Equal (default)
ne: Not equal
gt: Greater than
lt: Less than
ge: Greater than or equal
le: Less than or equal
sa: Starts after
eb: Ends before
ap: Approximately (~10%)

Common Modifiers
:missing (All single-element types): Filter by presence/absence of value
:exact (string): Case-sensitive exact match
:contains (string, uri): Match anywhere in value
:text (token, reference): String match on display text
:not (token): Negation
:above (token, reference, uri): Hierarchical/subsumption search (ancestors)
:below (token, reference, uri): Hierarchical/subsumption search (descendants)
:in (token): Value is in specified ValueSet
:not-in (token): Value is not in specified ValueSet
:identifier (reference): Match on Reference.identifier
:[type] (reference): Restrict reference to specific resource type
:of-type (token): Match identifier by type code and value
"""


# ============================================================================
# Create Query Agent Models
# ============================================================================

class CreateQueryOutput(BaseModel):
    """Generated query string"""
    query_string: Annotated[
        str,
        StringConstraints(
            min_length=1,
            strip_whitespace=True,
        ),
        Field(
            description="The FHIR search query string to append to the resource endpoint",
            examples=["name=John&birthdate=gt1990-01-01"]
        )
    ]


class CreateQueryError(BaseModel):
    """Error result when query creation fails"""
    error: str = Field(
        description="Error message describing what went wrong"
    )
    suggestion: str | None = Field(
        default=None,
        description="Suggested alternative approaches or corrections"
    )


# ============================================================================
# Create Query Agent Class
# ============================================================================

class CreateQueryAgent:
    def __init__(self, target_type: str, metadata: FHIRMetadata, common_search_params: list[SearchParameter]):
        self.target_type = target_type
        self.metadata = metadata
        self.common_search_params = common_search_params

        self.model = AnthropicModel('claude-opus-4-5')
        self.agent = Agent(
            model=self.model,
            output_type=CreateQueryOutput | CreateQueryError,
            system_prompt=self._build_system_prompt()
        )

    def _build_system_prompt(self) -> str:
        """Build dynamic system prompt with available types from metadata"""
        target_type_metadata = self.metadata.resource_metadata.get(self.target_type, None)
        if target_type_metadata is None:
            raise ValueError(f"Target type {self.target_type} not found in metadata")

        # Avoid reusing common search params that were already provided in metadata
        metadata_search_params: set[str] = set([n.name for n in target_type_metadata.search_params])
        available_search_params: list[SearchParameter] = [p for p in target_type_metadata.search_params] + [p for p in self.common_search_params if p.name not in metadata_search_params]
        available_search_params.sort(key=lambda p: p.name)

        available_include_values = target_type_metadata.include_values
        available_include_values.sort()

        available_revinclude_values = target_type_metadata.revinclude_values
        available_revinclude_values.sort()

        # Stringify the lists for the prompt
        search_params_str = "\n".join([f"  - {str(param)}" for param in available_search_params])
        include_values_str = "\n".join([f"  - {val}" for val in available_include_values])
        revinclude_values_str = "\n".join([f"  - {val}" for val in available_revinclude_values])

        return f"""You are a FHIR query builder. Build a valid FHIR search query string for the '{self.target_type}' resource type.

TARGET RESOURCE TYPE: {self.target_type}

AVAILABLE SEARCH PARAMETERS ({len(available_search_params)} total):
{search_params_str}

AVAILABLE _include VALUES ({len(available_include_values)} total):
{include_values_str}

AVAILABLE _revinclude VALUES ({len(available_revinclude_values)} total):
{revinclude_values_str}

{SYNTAX_SUMMARY_PROMPT}

Your task:
1. Analyze the user's query to understand what data they want to search for
2. Select appropriate search parameters from the available list above
3. Build a valid FHIR search query string using the correct syntax
4. Use appropriate modifiers, prefixes, and combinators based on the parameter types
5. Return the complete query string that can be appended to /{self.target_type}?
6. If a correct, valid query string cannot be generated for some reason, output the error. If there is not enough information to ouput a valid query string, you must output an error.

IMPORTANT:
- Only use search parameters from the available list above
- Follow FHIR R4 search syntax rules
- Use correct parameter types and modifiers
"""
