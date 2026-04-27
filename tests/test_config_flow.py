"""Tests for config_flow validation helpers."""
import re
import pytest

# Import the private validator directly
from custom_components.eau_grand_lyon.config_flow import _validate_email
import voluptuous as vol


class TestValidateEmail:
    def test_valid_email_passes(self):
        assert _validate_email("user@example.com") == "user@example.com"

    def test_strips_whitespace(self):
        assert _validate_email("  user@example.com  ") == "user@example.com"

    def test_subdomain_email_passes(self):
        assert _validate_email("user@mail.example.co.uk") == "user@mail.example.co.uk"

    def test_plus_tag_passes(self):
        assert _validate_email("user+tag@example.com") == "user+tag@example.com"

    def test_missing_at_raises(self):
        with pytest.raises(vol.Invalid):
            _validate_email("notanemail")

    def test_missing_domain_raises(self):
        with pytest.raises(vol.Invalid):
            _validate_email("user@")

    def test_missing_local_raises(self):
        with pytest.raises(vol.Invalid):
            _validate_email("@example.com")

    def test_empty_string_raises(self):
        with pytest.raises(vol.Invalid):
            _validate_email("")

    def test_spaces_only_raises(self):
        with pytest.raises(vol.Invalid):
            _validate_email("   ")
