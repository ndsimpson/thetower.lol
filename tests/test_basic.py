"""Basic tests for thetower package."""


def test_thetower_package_imports():
    """Test that the main package can be imported."""
    import thetower
    assert thetower.__version__ == "1.0.0"


def test_package_structure():
    """Test that the package has expected structure."""
    import thetower
    # Basic import test - more tests will be added as we migrate components
    assert hasattr(thetower, '__version__')
