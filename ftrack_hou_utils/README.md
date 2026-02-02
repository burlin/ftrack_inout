# Ftrack Houdini Utilities

A collection of utilities for integrating Ftrack with Houdini, providing template-based asset loading, node management, and configuration.

## Features

- **Template System**
  - YAML-based template configuration
  - JSON Schema validation
  - Category-based organization
  - Parameter validation and defaults
  - Support for multiple template types:
    - FBX character (geometry, pose, animation)
    - FBX animation
    - Alembic cache
    - USD asset
    - Image sequence

- **Node Management**
  - Improved parameter handling
  - Color-coded node connections
  - Enhanced error handling
  - Type hints and documentation
  - Template-based node creation
  - Python SOP for Ftrack attributes

- **Configuration System**
  - Centralized color schemes
  - Logging configuration with rotation
  - API settings with retry and caching
  - Template validation schema
  - User-specific configuration
  - Path management

- **Logging System**
  - Centralized configuration
  - Function and method decorators
  - Timing and performance tracking
  - Detailed error logging
  - Multiple handlers
  - LoggerMixin for classes

## Installation

```bash
pip install ftrack-hou-utils
```

For development installation:

```bash
pip install -e ".[dev,test,docs]"
```

## Quick Start

```python
from ftrack_hou_utils import initialize, TemplateManager

# Initialize the utilities
template_manager = initialize()

# Load a template
template = template_manager.get_template("character_fbx")

# Create nodes from template
nodes = template_manager.create_nodes_from_template(template)
```

## Configuration

Create a `templates.yaml` file in your Houdini config directory:

```yaml
character_fbx:
  name: Character FBX
  category: character
  outputs:
    - name: geometry
      type: sop
      color: blue
    - name: pose
      type: sop
      color: green
    - name: animation
      type: sop
      color: red
```

## Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ftrack_hou_utils.git
cd ftrack_hou_utils
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Install development dependencies:
```bash
pip install -e ".[dev,test,docs]"
```

4. Run tests:
```bash
pytest
```

## Documentation

Full documentation is available at [https://ftrack-hou-utils.readthedocs.io/](https://ftrack-hou-utils.readthedocs.io/)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to the Ftrack team for their excellent API
- Thanks to SideFX for Houdini's amazing Python integration
- Thanks to all contributors who have helped with this project

## Support

If you encounter any problems, please [file an issue](https://github.com/yourusername/ftrack_hou_utils/issues) along with a detailed description. 