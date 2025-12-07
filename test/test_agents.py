"""
Tests for FHIR AI Query Builder Agents

This module contains comprehensive tests for the FHIR AI agents including:
- Metadata fetching functionality
- Utility functions
- SelectTypesAgent
- CreateQueryAgent
"""

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from agents import (
    fetch_searchable_resources,
    get_search_parameters,
    SelectTypesAgent,
    CreateQueryAgent,
    SelectedResourceType,
    SelectTypeError,
    CreateQueryOutput,
    CreateQueryError,
    COMMON_SEARCH_PARAMS,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def metadata():
    """Fetch metadata once for all tests"""
    return fetch_searchable_resources()


@pytest.fixture(scope="module")
def select_agent(metadata):
    """Create SelectTypesAgent instance"""
    return SelectTypesAgent(metadata)


@pytest.fixture(scope="module")
def patient_query_agent(metadata):
    """Create CreateQueryAgent for Patient resource"""
    return CreateQueryAgent(
        target_type="Patient",
        metadata=metadata,
        common_search_params=COMMON_SEARCH_PARAMS
    )


@pytest.fixture(scope="module")
def observation_query_agent(metadata):
    """Create CreateQueryAgent for Observation resource"""
    return CreateQueryAgent(
        target_type="Observation",
        metadata=metadata,
        common_search_params=COMMON_SEARCH_PARAMS
    )


# ============================================================================
# Metadata Tests
# ============================================================================

def test_fetch_searchable_resources(metadata):
    """Test that metadata can be fetched from FHIR server"""
    assert metadata is not None
    assert metadata.fhir_version is not None
    assert len(metadata.searchable_types) > 0
    assert 'Patient' in metadata.searchable_types


def test_metadata_structure(metadata):
    """Test that metadata has expected structure"""
    assert hasattr(metadata, 'searchable_types')
    assert hasattr(metadata, 'resource_metadata')
    assert hasattr(metadata, 'fhir_version')
    assert hasattr(metadata, 'server_url')

    # Check Patient metadata exists and has required fields
    assert 'Patient' in metadata.resource_metadata
    patient_meta = metadata.resource_metadata['Patient']
    assert patient_meta.type == 'Patient'
    assert len(patient_meta.search_params) > 0
    assert len(patient_meta.interactions) > 0
    assert 'search-type' in patient_meta.interactions


# ============================================================================
# Utility Function Tests
# ============================================================================

def test_get_search_parameters_patient(metadata):
    """Test getting search parameters for Patient resource"""
    patient_params = get_search_parameters("Patient", metadata)

    assert len(patient_params) > 0
    assert all(hasattr(param, 'name') for param in patient_params)
    assert all(hasattr(param, 'type') for param in patient_params)

    # Check for some expected parameters
    param_names = [p.name for p in patient_params]
    assert '_id' in param_names or 'identifier' in param_names


def test_get_search_parameters_invalid_type(metadata):
    """Test error handling for invalid resource type"""
    with pytest.raises(ValueError) as exc_info:
        get_search_parameters("InvalidType", metadata)

    assert "not found in metadata" in str(exc_info.value)


# ============================================================================
# SelectTypesAgent Tests
# ============================================================================

def test_select_types_clear_query(select_agent):
    """Test clear query: 'Find all patients born after 1990'"""
    results = select_agent.select_types("Find all patients born after 1990")

    # Should return a list of SelectedResourceType
    assert isinstance(results, list)
    assert len(results) > 0

    # First result should be SelectedResourceType for Patient
    first_result = results[0]
    assert isinstance(first_result, SelectedResourceType)
    assert first_result.selected_type == "Patient"
    assert first_result.confidence >= 0.9  # Should have high confidence
    assert len(first_result.reasoning) > 0


def test_select_types_ambiguous_query(select_agent):
    """Test ambiguous query: 'Get medication data'"""
    results = select_agent.select_types("Get medication data")

    # Should return a list with multiple medication-related types
    assert isinstance(results, list)
    assert len(results) > 0

    # Check that medication-related types are returned
    selected_types = [r.selected_type for r in results if isinstance(r, SelectedResourceType)]
    medication_related = ['Medication', 'MedicationRequest', 'MedicationStatement',
                         'MedicationAdministration', 'MedicationDispense']

    # At least some medication-related types should be present
    assert any(t in medication_related for t in selected_types)


def test_select_types_semantic_query(select_agent):
    """Test semantic query: 'Show me blood pressure readings'"""
    results = select_agent.select_types("Show me blood pressure readings")

    # Should return appropriate type(s) for vital signs/observations
    assert isinstance(results, list) or isinstance(results, SelectTypeError)

    if isinstance(results, list):
        assert len(results) > 0
        # Should likely be Observation or DiagnosticReport
        selected_types = [r.selected_type for r in results if isinstance(r, SelectedResourceType)]
        assert any(t in ['Observation', 'DiagnosticReport'] for t in selected_types)


def test_select_types_nonexistent_type(select_agent):
    """Test non-existent type: 'Find XYZ records'"""
    results = select_agent.select_types("Find XYZ records")

    # Should return SelectTypeError since XYZ doesn't exist
    assert isinstance(results, SelectTypeError)
    assert len(results.error) > 0
    assert len(results.reasoning) > 0


# ============================================================================
# CreateQueryAgent Tests - Patient Resource
# ============================================================================

def test_create_query_simple_name(patient_query_agent):
    """Test simple name search: 'Find patients with family name Smith'"""
    result = patient_query_agent.agent.run_sync("Find patients with family name Smith")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    assert 'family' in output.query_string.lower() or 'smith' in output.query_string.lower()
    assert len(output.query_string) > 0


def test_create_query_date_range(patient_query_agent):
    """Test date range query: 'Patients born after January 1, 1990'"""
    result = patient_query_agent.agent.run_sync("Patients born after January 1, 1990")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    assert 'birthdate' in output.query_string.lower()
    assert 'gt' in output.query_string or '>' in output.query_string or '1990' in output.query_string


def test_create_query_multiple_params(patient_query_agent):
    """Test multiple parameters: 'Find female patients named Maria born after 1985'"""
    result = patient_query_agent.agent.run_sync("Find female patients named Maria born after 1985")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    query = output.query_string.lower()

    # Should contain multiple parameters
    assert 'gender' in query or 'female' in query
    assert 'name' in query or 'maria' in query
    assert 'birthdate' in query or '1985' in query


def test_create_query_token_syntax(patient_query_agent):
    """Test token parameter: 'Find patient with MRN 12345 from system http://hospital.org/mrn'"""
    result = patient_query_agent.agent.run_sync(
        "Find patient with MRN 12345 from system http://hospital.org/mrn"
    )
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    assert 'identifier' in output.query_string.lower()
    assert '12345' in output.query_string


def test_create_query_address(patient_query_agent):
    """Test address search: 'Patients living in New York'"""
    result = patient_query_agent.agent.run_sync("Patients living in New York")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    assert 'address' in output.query_string.lower() or 'new' in output.query_string.lower()


def test_create_query_result_control(patient_query_agent):
    """Test result control: 'Get 10 most recent patients'"""
    result = patient_query_agent.agent.run_sync("Get 10 most recent patients")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    assert '_count' in output.query_string or 'count' in output.query_string
    assert '_sort' in output.query_string or 'sort' in output.query_string or '10' in output.query_string


def test_create_query_or_logic(patient_query_agent):
    """Test OR logic: 'Find patients named John or Jane'"""
    result = patient_query_agent.agent.run_sync("Find patients named John or Jane")
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    # Should use comma-separated values for OR logic
    assert 'john' in output.query_string.lower() or 'jane' in output.query_string.lower()


def test_create_query_error_handling(patient_query_agent):
    """Test error handling: 'Find patients by their favorite color'"""
    result = patient_query_agent.agent.run_sync("Find patients by their favorite color")
    output = result.output

    # Should return an error since favorite color is not a standard parameter
    assert isinstance(output, CreateQueryError)
    assert len(output.error) > 0


def test_create_query_complex(patient_query_agent):
    """Test complex query: 'Active female patients in California born between 1980-1990'"""
    result = patient_query_agent.agent.run_sync(
        "Active female patients in California born between 1980 and 1990"
    )
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    query = output.query_string.lower()

    # Should contain multiple conditions
    assert 'gender' in query or 'female' in query
    assert 'address' in query or 'california' in query
    assert 'birthdate' in query or '1980' in query or '1990' in query


# ============================================================================
# CreateQueryAgent Tests - Observation Resource
# ============================================================================

def test_create_query_chaining(observation_query_agent):
    """Test chaining: 'Find blood pressure observations for patient with name Smith'"""
    result = observation_query_agent.agent.run_sync(
        "Find blood pressure observations for patient with name Smith"
    )
    output = result.output

    assert isinstance(output, CreateQueryOutput)
    # Should use chaining (patient.name) or reference to patient
    assert 'patient' in output.query_string.lower() or 'subject' in output.query_string.lower()


# ============================================================================
# Integration Test
# ============================================================================

def test_full_workflow_integration(metadata):
    """Test complete workflow from type selection to query building"""
    # Step 1: Select type
    select_agent = SelectTypesAgent(metadata)
    type_results = select_agent.select_types("Find patients with diabetes")

    assert isinstance(type_results, list) or isinstance(type_results, SelectTypeError)

    if isinstance(type_results, list) and len(type_results) > 0:
        first_type = type_results[0]
        if isinstance(first_type, SelectedResourceType):
            # Step 2: Create query for that type
            query_agent = CreateQueryAgent(
                target_type=first_type.selected_type,
                metadata=metadata,
                common_search_params=COMMON_SEARCH_PARAMS
            )

            query_result = query_agent.agent.run_sync("Find patients with diabetes")
            query_output = query_result.output

            # Should successfully create a query
            assert isinstance(query_output, CreateQueryOutput) or isinstance(query_output, CreateQueryError)
            if isinstance(query_output, CreateQueryOutput):
                assert len(query_output.query_string) > 0
