import pytest

from src.drivers.circutor import CircutorDriver
from src.drivers.entes import EntesDriver
from src.drivers.greenlee import GreenleeDriver
from src.drivers.registry import DriverResolutionError, build_all_drivers, build_driver


@pytest.fixture
def full_config(greenlee_config, entes_config, circutor_config):
    return {
        "ammeters": {
            "greenlee": greenlee_config,
            "entes": entes_config,
            "circutor": circutor_config,
        }
    }


@pytest.mark.parametrize(
    "name,expected_class",
    [
        ("greenlee", GreenleeDriver),
        ("entes", EntesDriver),
        ("circutor", CircutorDriver),
    ],
)
def test_build_driver_resolves_expected_class(full_config, name, expected_class):
    driver = build_driver(name, full_config["ammeters"][name])
    assert isinstance(driver, expected_class)


def test_build_all_drivers_returns_all_three(full_config):
    drivers = build_all_drivers(full_config)

    assert set(drivers.keys()) == {"greenlee", "entes", "circutor"}
    assert isinstance(drivers["greenlee"], GreenleeDriver)
    assert isinstance(drivers["entes"], EntesDriver)
    assert isinstance(drivers["circutor"], CircutorDriver)


def test_build_driver_missing_driver_key_raises(greenlee_config):
    del greenlee_config["driver"]
    with pytest.raises(DriverResolutionError):
        build_driver("greenlee", greenlee_config)


def test_build_driver_unresolvable_module_raises(greenlee_config):
    greenlee_config["driver"] = "src.drivers.nonexistent.NoSuchDriver"
    with pytest.raises(DriverResolutionError):
        build_driver("greenlee", greenlee_config)


def test_build_driver_unresolvable_class_raises(greenlee_config):
    greenlee_config["driver"] = "src.drivers.greenlee.NoSuchClass"
    with pytest.raises(DriverResolutionError):
        build_driver("greenlee", greenlee_config)


def test_build_driver_non_dotted_path_raises(greenlee_config):
    greenlee_config["driver"] = "NotDotted"
    with pytest.raises(DriverResolutionError):
        build_driver("greenlee", greenlee_config)


def test_build_driver_wrong_class_type_raises(greenlee_config):
    greenlee_config["driver"] = "src.drivers.base.MeasurementSample"
    with pytest.raises(DriverResolutionError):
        build_driver("greenlee", greenlee_config)
