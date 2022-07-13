""" This module contains all geometry conversion functionality To and From Speckle."""
from speckle.logging import logger
from typing import List, Union

from qgis.core import (
    QgsGeometry,
    QgsWkbTypes,
    QgsMultiPoint,
    QgsMultiLineString,
    QgsMultiPolygon,
)
from speckle.converter.geometry.mesh import meshToNative
from speckle.converter.geometry.point import pointToNative, pointToSpeckle
from speckle.converter.geometry.polygon import *
from speckle.converter.geometry.polyline import (
    lineToNative,
    polylineToNative,
    curveToNative,
    polylineToSpeckle,
    circleToNative,
    arcToNative,
    arcToSpeckle,
    polycurveToNative,
)
from specklepy.objects import Base
from specklepy.objects.geometry import (
    Line,
    Mesh,
    Point,
    Polyline,
    Curve,
    Arc,
    Circle,
    Polycurve,
)


def convertToSpeckle(
    feature: QgsFeature, layer: QgsVectorLayer
) -> Union[Base, List[Base], None]:
    """Converts the provided layer feature to Speckle objects"""

    if isinstance(feature, QgsGeometry):
        geom = feature
    else:
        geom = feature.geometry()

    if isinstance(geom, QgsFeature):
        return

    geomSingleType = QgsWkbTypes.isSingleType(geom.wkbType())
    geomType = geom.type()
    type = geom.wkbType()

    if geomType == QgsWkbTypes.PointGeometry:
        # the geometry type can be of single or multi type
        if geomSingleType:
            return pointToSpeckle(geom.constGet(), feature, layer)
        else:
            return [pointToSpeckle(pt, feature, layer) for pt in geom.parts()]

    elif geomType == QgsWkbTypes.LineGeometry:
        if (
            type == QgsWkbTypes.CircularString
            or type == QgsWkbTypes.CircularStringZ
            or type == QgsWkbTypes.CircularStringM
            or type == QgsWkbTypes.CircularStringZM
        ):  # Type (not GeometryType)
            if geomSingleType:
                return arcToSpeckle(geom, feature, layer)
            else:
                return [arcToSpeckle(poly, feature, layer) for poly in geom.parts()]

        if geomSingleType:
            return polylineToSpeckle(geom, feature, layer)
        else:
            return [polylineToSpeckle(poly, feature, layer) for poly in geom.parts()]
    elif geomType == QgsWkbTypes.PolygonGeometry:
        if geomSingleType:
            return polygonToSpeckle(geom, feature, layer)
        else:
            return [polygonToSpeckle(p, feature, layer) for p in geom.parts()]
    else:
        logger.log("Unsupported or invalid geometry")
    return None


def convertToNative(base: Base) -> Union[QgsGeometry, None]:
    """Converts any given base object to QgsGeometry."""
    converted = None
    conversions = [
        (Point, pointToNative),
        (Line, lineToNative),
        (Polyline, polylineToNative),
        (Curve, curveToNative),
        (Arc, arcToNative),
        (Circle, circleToNative),
        (Mesh, meshToNative),
        (Polycurve, polycurveToNative),
        (
            Base,
            polygonToNative,
        ),  # temporary solution for polygons (Speckle has no type Polygon yet)
    ]

    for conversion in conversions:
        if isinstance(base, conversion[0]):
            # print(conversion[0])
            converted = conversion[1](base)
            break

    return converted


def multiPointToNative(items: List[Point]):
    pts = QgsMultiPoint()
    for item in items:
        g = pointToNative(item)
        if g is not None:
            pts.addGeometry(g)
    return pts


def multiPolylineToNative(items: List[Polyline]):
    polys = QgsMultiLineString()
    for item in items:
        g = polylineToNative(item)
        if g is not None:
            polys.addGeometry(g)
    return polys


def multiPolygonToNative(items: List[Base]):
    polygons = QgsMultiPolygon()
    for item in items:
        g = polygonToNative(item)
        if g is not None:
            polygons.addGeometry(g)
    return polygons


def convertToNativeMulti(items: List[Base]):
    first = items[0]
    if isinstance(first, Point):
        return multiPointToNative(items)
    elif isinstance(first, Line) or isinstance(first, Polyline):
        return multiPolylineToNative(items)
    elif first["boundary"] is not None and first["voids"] is not None:
        return multiPolygonToNative(items)
