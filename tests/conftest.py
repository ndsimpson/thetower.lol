"""
Test configuration for Tower project.

This file contains pytest configuration and shared fixtures.
"""
import os
import sys

import pytest

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {
        'tournament_id': 'test_tournament_123',
        'player_id': 'test_player_456',
        'league': 'Champion'
    }
