"""resolvekit.errors — public error exports.

All exception classes that resolvekit can raise are re-exported here.
Catch from this namespace for stable, version-proof exception handling.

Example::

    from resolvekit.errors import AmbiguousResolutionError, DataPackNotAvailableError
"""

from resolvekit.core.errors import (
    AmbiguousLinkError,
    AmbiguousResolutionError,
    CrosswalkError,
    DataModuleNotFoundError,
    DataPackError,
    DataPackNormalizerVersionError,
    DataPackNotAvailableError,
    DataPackRuntimeVersionError,
    EntityNotFoundError,
    GroupNotFoundError,
    IncompatibleFeatureSchemaError,
    IncompatibleVersionError,
    InvalidKeyError,
    LinkError,
    MissingModuleDependencyError,
    ModuleConflictError,
    ModuleRegistryError,
    NoModulesInstalledError,
    OutputMissingError,
    OverlayConstraintError,
    RegistryError,
    ResolutionError,
    UnknownCodeSystemError,
    UnknownDomainError,
    UnknownOutputError,
    UnsupportedStoreError,
)
from resolvekit.core.errors_base import ExplainNotAvailableError, ResolverError

__all__ = [
    "AmbiguousLinkError",
    "AmbiguousResolutionError",
    "CrosswalkError",
    "DataModuleNotFoundError",
    "DataPackError",
    "DataPackNormalizerVersionError",
    "DataPackNotAvailableError",
    "DataPackRuntimeVersionError",
    "EntityNotFoundError",
    "ExplainNotAvailableError",
    "GroupNotFoundError",
    "IncompatibleFeatureSchemaError",
    "IncompatibleVersionError",
    "InvalidKeyError",
    "LinkError",
    "MissingModuleDependencyError",
    "ModuleConflictError",
    "ModuleRegistryError",
    "NoModulesInstalledError",
    "OutputMissingError",
    "OverlayConstraintError",
    "RegistryError",
    "ResolutionError",
    "ResolverError",
    "UnknownCodeSystemError",
    "UnknownDomainError",
    "UnknownOutputError",
    "UnsupportedStoreError",
]
