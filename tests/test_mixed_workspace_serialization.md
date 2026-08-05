# Mixed workspace serialization regression

The native Theia workspace service is expected to keep `ra-remote://` roots unchanged when local `file://` roots are added or removed. The executable regression coverage is implemented in `tests/test_theia_desktop_frontend.py`, while the production TypeScript build validates the custom `WorkspaceService` override.
