# Contributing to Gree Climate Cloud

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Code of Conduct

Be respectful, inclusive, and constructive in all interactions.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/dawidrashid/homeassistant-gree-cloud/issues)
2. If not, create a new issue with:
   - Clear, descriptive title
   - Steps to reproduce
   - Expected vs actual behavior
   - Home Assistant version
   - Integration version
   - Relevant log output (with debug logging enabled)

### Suggesting Features

1. Check if the feature has already been suggested
2. Create an issue describing:
   - The problem you're trying to solve
   - Your proposed solution
   - Any alternatives you've considered

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes following the code style guidelines
4. Test your changes thoroughly
5. Commit with clear, descriptive messages
6. Push to your fork
7. Create a Pull Request

## Development Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed setup instructions.

## Code Style

### Python

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Use type hints for function parameters and return values
- Maximum line length: 88 characters (Black formatter)
- Use meaningful variable and function names

### Example

```python
async def async_set_temperature(self, **kwargs: Any) -> None:
    """Set new target temperature.
    
    Args:
        kwargs: Keyword arguments including temperature and optionally hvac_mode
        
    Raises:
        ValueError: If temperature parameter is missing
    """
    if ATTR_TEMPERATURE not in kwargs:
        raise ValueError(f"Missing parameter {ATTR_TEMPERATURE}")
    
    temperature = kwargs[ATTR_TEMPERATURE]
    self.coordinator.device.target_temperature = temperature
    await self.coordinator.push_state_update()
```

### Docstrings

Use Google-style docstrings:

```python
def function_name(param1: str, param2: int) -> bool:
    """Short description.
    
    Longer description if needed.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        ExceptionType: Description of when this is raised
    """
```

## Testing

### Manual Testing

1. Install the integration in a test Home Assistant instance
2. Configure with real Gree+ credentials
3. Verify all functionality works:
   - Device discovery
   - Climate entity controls
   - Switch entity controls
   - State updates
   - Error handling

### Test Checklist

- [ ] Integration loads successfully
- [ ] Config flow works correctly
- [ ] Devices are discovered
- [ ] Climate entity responds to commands
- [ ] Switch entities work
- [ ] State updates after 60 seconds
- [ ] Handles device offline gracefully
- [ ] Handles authentication errors
- [ ] No errors in logs during normal operation

## Project Structure

```
custom_components/gree_cloud/
├── __init__.py           # Entry point, setup/unload
├── config_flow.py        # UI configuration flow
├── const.py             # Constants
├── coordinator.py       # Update coordinator, discovery
├── entity.py            # Base entity class
├── climate.py           # Climate entity
├── switch.py            # Switch entities
├── manifest.json        # Metadata
├── strings.json         # UI strings
└── translations/        # Localized strings
```

## Areas for Contribution

### High Priority

- **Additional language translations**: Currently only English is supported
- **Cipher v2 support UI**: Expose cipher version selection in config flow
- **Better error messages**: More descriptive error messages for users
- **State change notifications**: Notify when device state changes externally

### Medium Priority

- **Multiple account support**: Support multiple Gree+ accounts
- **Device grouping**: Group devices by home/room from Gree+ app
- **Advanced features**: Expose more device properties (if available)
- **Better offline handling**: Improve behavior when devices go offline

### Low Priority

- **Custom update interval**: Allow users to configure polling interval
- **Statistics**: Track energy usage, runtime, etc.
- **Icons**: Custom icons for different device types

## Questions?

If you have questions about contributing, feel free to:
- Open an issue with the "question" label
- Contact the maintainer

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
