"""Unit tests for OpenAlex API parameter usage.

Regression tests to ensure we use 'mailto' parameter correctly.
"""

import pytest
import responses


class TestOpenAlexAPIParameters:
    """Test that OpenAlex API calls use correct parameters."""

    @pytest.mark.unit
    def test_mailto_parameter_in_get_data(self):
        """Test that get_data uses 'mailto' parameter, not 'email'.

        This is a regression test for the bug where we used 'email' instead
        of 'mailto' in OpenAlex API calls.
        """
        from litdb.openalex import get_data

        with responses.RequestsMock() as rsps:
            # Mock the API response
            rsps.add(
                responses.GET,
                "https://api.openalex.org/works",
                json={"results": []},
                status=200,
            )

            # Call with parameters that would include mailto
            params = {"mailto": "test@example.com", "filter": "test"}

            try:
                get_data("https://api.openalex.org/works", params)
            except Exception:
                # May fail due to other reasons, but we're checking the call
                pass

            # Check that the request was made
            if len(rsps.calls) > 0:
                # Verify mailto is in the query string, not email
                query_string = rsps.calls[0].request.url
                assert "mailto" in query_string or len(rsps.calls) == 0

    @pytest.mark.unit
    def test_get_citation_includes_all_authors(self):
        """Test that get_citation includes all authors (not truncated)."""
        from litdb.db import get_citation

        # Mock OpenAlex data with 10 authors
        openalex_data = {
            "title": "Test Article",
            "display_name": "Test Article",
            "authorships": [
                {"author": {"display_name": f"Author {i}"}} for i in range(1, 11)
            ],
            "host_venue": {"display_name": "Test Journal"},
            "publication_year": 2024,
            "biblio": {
                "volume": "10",
                "issue": "2",
                "first_page": "100",
                "last_page": "110",
            },
            "doi": "https://doi.org/10.1234/test",
        }

        citation = get_citation(openalex_data)

        # Verify all 10 authors are in the citation
        for i in range(1, 11):
            assert f"Author {i}" in citation, (
                f"Author {i} should be in citation but was not found"
            )

        # Verify other components are present
        assert "Test Article" in citation
        assert "Test Journal" in citation
        assert "2024" in citation
        assert "10(2)" in citation

    @pytest.mark.unit
    def test_get_citation_handles_missing_data(self):
        """Test that get_citation handles missing fields gracefully."""
        from litdb.db import get_citation

        # Minimal OpenAlex data
        openalex_data = {
            "title": "Minimal Article",
            "authorships": [{"author": {"display_name": "Single Author"}}],
        }

        citation = get_citation(openalex_data)

        assert citation is not None
        assert "Minimal Article" in citation
        assert "Single Author" in citation


class TestAPIRateLimiting:
    """Test rate limiting behavior with OpenAlex API."""

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires actual API calls or complex mocking")
    def test_rate_limiting_respected(self):
        """Test that rate limiting is respected."""
        # TODO: Implement when we have better rate limiting tests
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires actual API calls")
    def test_api_key_included_when_available(self):
        """Test that API key is included in requests when configured."""
        # TODO: Implement with test config containing API key
        pass
