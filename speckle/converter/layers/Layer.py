from typing import Any, Dict, List, Optional
from specklepy.objects.base import Base

from speckle.converter.layers import CRS


class Layer(Base, chunkable={"features": 100}):
    """A GIS Layer"""

    def __init__(
        self,
        name: Optional[str] = None,
        crs: Optional[CRS] = None,
        features: List[Base] = [],
        layerType: str = "None",
        geomType: str = "None",
        renderer: Dict[str, Any] = {},
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.crs = crs
        self.type = layerType
        self.features = features
        self.geomType = geomType
        self.renderer = renderer


class RasterLayer(Base, chunkable={"features": 100}):
    """A GIS Layer"""

    def __init__(
        self,
        name: Optional[str] = None,
        crs: Optional[str] = None,
        rasterCrs: Optional[str] = None,
        features: List[Base] = [],
        layerType: str = "None",
        geomType: str = "None",
        renderer: Dict[str, Any] = {},
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.crs = crs
        self.rasterCrs = rasterCrs
        self.type = layerType
        self.features = features
        self.geomType = geomType
        self.renderer = renderer
