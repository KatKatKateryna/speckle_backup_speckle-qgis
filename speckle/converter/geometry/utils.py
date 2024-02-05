import inspect
from math import asin, cos, sin, atan
import math
import random
from specklepy.objects.geometry import (
    Point,
    Line,
    Polyline,
    Circle,
    Arc,
    Polycurve,
    Vector,
)
from specklepy.objects import Base
from typing import List, Tuple, Union, Dict
from speckle.converter.geometry.point import applyOffsetsRotation

from shapely.geometry import Polygon
from shapely.ops import triangulate
import shapely.wkt
import geopandas as gpd
from geovoronoi import voronoi_regions_from_coords

# from speckle.converter.geometry.polyline import speckleArcCircleToPoints, specklePolycurveToPoints
from speckle.utils.panel_logging import logToUser

# import time

import numpy as np

from qgis.core import (
    Qgis,
    QgsProject,
    QgsLayerTreeLayer,
    QgsFeature,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsPoint,
)


def cross_product(pt1, pt2):
    return [
        (pt1[1] * pt2[2]) - (pt1[2] * pt2[1]),
        (pt1[2] * pt2[0]) - (pt1[0] * pt2[2]),
        (pt1[0] * pt2[1]) - (pt1[1] * pt2[0]),
    ]


def dot(pt1: List, pt2: List):
    return (pt1[0] * pt2[0]) + (pt1[1] * pt2[1]) + (pt1[2] * pt2[2])


def normalize(pt: List, tolerance=1e-10):
    magnitude = dot(pt, pt) ** 0.5
    if abs(magnitude - 1) < tolerance:
        return pt

    if magnitude != 0:
        scale = 1.0 / magnitude
    else:
        scale = 1.0
    normalized_vector = [coordinate * scale for coordinate in pt]
    return normalized_vector


def createPlane(pt1: List, pt2: List, pt3: List):
    vector1to2 = [pt2[0] - pt1[0], pt2[1] - pt1[1], pt2[2] - pt1[2]]
    vector1to3 = [pt3[0] - pt1[0], pt3[1] - pt1[1], pt3[2] - pt1[2]]

    u_direction = normalize(vector1to2)
    normal = cross_product(u_direction, vector1to3)
    return {"origin": pt1, "normal": normal}


def project_to_plane_on_z(point: List, plane: Dict):
    d = dot(plane["normal"], plane["origin"])
    z_value_on_plane = (
        d - (plane["normal"][0] * point[0]) - (plane["normal"][1] * point[1])
    ) / plane["normal"][2]
    return z_value_on_plane


def projectToPolygon(point: List, polygonPts: List):
    if len(polygonPts) < 3:
        return 0
    pt1 = polygonPts[0]
    pt2 = polygonPts[1]
    pt3 = polygonPts[2]
    plane = createPlane(pt1, pt2, pt3)
    z = project_to_plane_on_z(point, plane)

    if z == -0.0:
        z = 0
    return z


def triangulatePolygon(geom, dataStorage):
    try:
        # import triangle as tr
        vertices = []  # only outer
        segments = []  # including holes
        holes = []
        pack = getPolyPtsSegments(geom, dataStorage)

        vertices, vertices3d, segments, holes = pack

        if len(vertices) > 0:
            vertices.append(vertices[0])
        for i, h in enumerate(holes):
            if len(holes[i]) > 0:
                holes[i].append(holes[i][0])
        dict_shape = {"vertices": vertices, "holes": holes}

        try:
            t, iterations = to_triangles(dict_shape, 0)
        except Exception as e:
            logToUser(e, level=2, func=inspect.stack()[0][3])
            return None, None, None
        return t, vertices3d, iterations

    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return None, None, None


def to_triangles(data, attempt=0):
    # https://gis.stackexchange.com/questions/316697/delaunay-triangulation-algorithm-in-shapely-producing-erratic-result
    try:
        vert_old = data["vertices"]
        holes_old = data["holes"]

        # round vertices:
        digits = 3 - attempt

        vert = []
        vert_rounded = []
        for i, v in enumerate(vert_old):
            if i == len(vert_old) - 1:
                vert.append(v)
                break  # don't test last point
            rounded = [round(v[0], digits), round(v[1], digits)]
            if v not in vert and rounded not in vert_rounded:
                vert.append(v)
                vert_rounded.append(rounded)

        # round holes:
        holes = []
        holes_rounded = []
        for k, h in enumerate(holes_old):
            hole = []
            for i, v in enumerate(h):
                if i == len(h) - 1:
                    hole.append(v)
                    break  # don't test last point
                rounded = [round(v[0], digits), round(v[1], digits)]
                if v not in holes and rounded not in holes_rounded:
                    hole.append(v)
                    holes_rounded.append(rounded)
            holes.append(hole)

        if len(holes) == 1 and len(holes[0]) == 0:
            polygon = Polygon([(v[0], v[1]) for v in vert])
        else:
            polygon = Polygon([(v[0], v[1]) for v in vert], holes)
        # polygon = Polygon([ ( v[0], v[1] ) for v in vert ] )
        # polygon = Polygon([(3.0, 0.0), (2.0, 0.0), (2.0, 0.75), (2.5, 0.75), (2.5, 0.6), (2.25, 0.6), (2.25, 0.2), (3.0, 0.2), (3.0, 0.0)])

        poly_points = []
        exterior_linearring = polygon.exterior
        poly_points += np.array(exterior_linearring.coords).tolist()

        try:
            polygon.interiors[0]
        except:
            poly_points = poly_points
        else:
            for i, interior_linearring in enumerate(polygon.interiors):
                a = interior_linearring.coords
                poly_points += np.array(a).tolist()

        poly_points = np.array(
            [item for sublist in poly_points for item in sublist]
        ).reshape(-1, 2)

        poly_shapes, pts = voronoi_regions_from_coords(
            poly_points, polygon.buffer(0.000001)
        )
        gdf_poly_voronoi = (
            gpd.GeoDataFrame({"geometry": poly_shapes}).explode().reset_index()
        )

        tri_geom = []
        for geom in gdf_poly_voronoi.geometry:
            inside_triangles = [
                tri for tri in triangulate(geom) if tri.centroid.within(polygon)
            ]
            tri_geom += inside_triangles

        vertices = []
        triangles = []
        for tri in tri_geom:
            xx, yy = tri.exterior.coords.xy
            v_list = zip(xx.tolist(), yy.tolist())

            tr_indices = []
            count = 0
            for vt in v_list:
                v = list(vt)
                if count == 3:
                    continue
                if v not in vertices:
                    vertices.append(v)
                    tr_indices.append(len(vertices) - 1)
                else:
                    tr_indices.append(vertices.index(v))
                count += 1
            triangles.append(tr_indices)

        shape = {"vertices": vertices, "triangles": triangles}
        return shape, attempt
    except Exception as e:
        print(e)
        attempt += 1
        if attempt <= 3:
            return to_triangles(data, attempt)
        else:
            return None, None


def getPolyPtsSegments(geom, dataStorage):
    vertices = []
    vertices3d = []
    segmList = []
    holes = []
    gv = list(geom.vertices())
    try:
        extRing = geom.exteriorRing()
        pt_iterator = extRing.vertices()
    except:
        try:
            extRing = geom.constGet().exteriorRing()
            pt_iterator = extRing.vertices()
        except:
            pt_iterator = geom.vertices()

    pointListLocal = []
    startLen = len(vertices)
    for i, pt in enumerate(pt_iterator):
        if (
            len(pointListLocal) > 0
            and pt.x() == pointListLocal[0].x()
            and pt.y() == pointListLocal[0].y()
        ):  # don't repeat 1st point
            pass
        else:
            pointListLocal.append(pt)
    for i, pt in enumerate(pointListLocal):
        x, y = applyOffsetsRotation(pt.x(), pt.y(), dataStorage)
        vertices.append([x, y])
        try:
            vertices3d.append([x, y, pt.z()])
        except:
            vertices3d.append([x, y, 0])

        # try: vertices3d.append([pt.x(),pt.y(),pt.z()])
        # except: vertices3d.append([pt.x(),pt.y(), 0]) # project boundary to 0
        if i > 0:
            segmList.append([startLen + i - 1, startLen + i])
        # if i == len(pointListLocal)-1: #also add a cap
        #    segmList.append([startLen+i, startLen])

    ########### get voids
    try:
        geom = geom.constGet()
    except:
        pass
    try:
        # logToUser(geom)
        intRingsNum = geom.numInteriorRings()
        # except:
        #    intRingsNum = len(geom.constParts())

        for k in range(intRingsNum):
            intRing = geom.interiorRing(k)
            pt_iterator = intRing.vertices()
            # pt_iterator = intRing.vertices()
            # intRing = geom.constParts(k)
            # intRing = geom.childGeometry(k)
            # pt_iterator = intRing.vertices()

            pt_list = list(pt_iterator)
            pointListLocal = []
            startLen = len(vertices)
            for i, pt in enumerate(pt_list):
                if (
                    len(pointListLocal) > 0
                    and pt.x() == pointListLocal[0].x()
                    and pt.y() == pointListLocal[0].y()
                ):  # don't repeat 1st point
                    continue
                elif [
                    pt.x(),
                    pt.y(),
                ] not in vertices:  # in case it's not the inner part of geometry
                    pointListLocal.append(pt)
                    # try:
                    #    pointListLocal.append([pt.x(), pt.y(), pt.z()])
                    # except:
                    #    pointListLocal.append([pt.x(), pt.y(), None])

            # hole = getHolePt(pointListLocal)
            # x, y = applyOffsetsRotation(hole[0], hole[1], dataStorage)

            if len(pointListLocal) > 2:
                holes.append(
                    [
                        applyOffsetsRotation(p.x(), p.y(), dataStorage)
                        for p in pointListLocal
                    ]
                )
            for i, pt in enumerate(pointListLocal):
                x, y = applyOffsetsRotation(pt.x(), pt.y(), dataStorage)
                # vertices.append([x, y])
                try:
                    vertices3d.append([x, y, pt.z()])
                except:
                    vertices3d.append([x, y, None])

                if i > 0:
                    segmList.append([startLen + i - 1, startLen + i])
                # if i == len(pointListLocal)-1: #also add a cap
                #    segmList.append([startLen+i, startLen])
    except Exception as e:
        logToUser(e, level=1, func=inspect.stack()[0][3])
    return vertices, vertices3d, segmList, holes


def fix_orientation(polyBorder, positive=True, coef=1):
    # polyBorder = [QgsPoint(-1.42681236722918436,0.25275926575812246), QgsPoint(-1.42314917758289616,0.78756097253123281), QgsPoint(-0.83703883417681257,0.77290957257654203), QgsPoint(-0.85169159276196471,0.24176979917208921), QgsPoint(-1.42681236722918436,0.25275926575812246)]
    sum_orientation = 0
    for k, ptt in enumerate(polyBorder):  # pointList:
        index = k + 1
        if k == len(polyBorder) - 1:
            index = 0
        pt = polyBorder[k * coef]
        pt2 = polyBorder[index * coef]
        # print(pt)
        try:
            sum_orientation += (pt2.x - pt.x) * (pt2.y + pt.y)  # if Speckle Points
        except:
            sum_orientation += (pt2.x() - pt.x()) * (pt2.y() + pt.y())  # if QGIS Points
    if positive is True:
        if sum_orientation < 0:
            polyBorder.reverse()
    else:
        if sum_orientation > 0:
            polyBorder.reverse()
    return polyBorder


def getHolePt(pointListLocal):
    pointListLocal = fix_orientation(pointListLocal, True, 1)
    minXpt = pointListLocal[0]
    index = 0
    index2 = 1
    for i, pt in enumerate(pointListLocal):
        if pt.x() < minXpt.x():
            minXpt = pt
            index = i
            if i == len(pointListLocal) - 1:
                index2 = 0
            else:
                index2 = index + 1
    x_range = pointListLocal[index2].x() - minXpt.x()
    y_range = pointListLocal[index2].y() - minXpt.y()
    if y_range > 0:
        sidePt = [minXpt.x() + abs(x_range / 2) + 0.001, minXpt.y() + y_range / 2]
    else:
        sidePt = [minXpt.x() + abs(x_range / 2) - 0.001, minXpt.y() + y_range / 2]
    return sidePt


def getPolygonFeatureHeight(feature, layer, dataStorage):
    height = None
    ignore = False
    if dataStorage.savedTransforms is not None:
        for item in dataStorage.savedTransforms:
            layer_name = item.split("  ->  ")[0].split(" ('")[0]
            transform_name = item.split("  ->  ")[1].lower()
            if "ignore" in transform_name:
                ignore = True

            if layer_name == layer.name():
                attribute = None
                if " ('" in item:
                    attribute = item.split(" ('")[1].split("') ")[0]

                if attribute is None and ignore is False:
                    logToUser(
                        "Attribute for extrusion not selected",
                        level=1,
                        func=inspect.stack()[0][3],
                    )
                    return None

                # print("Apply transform: " + transform_name)
                if "extrude" in transform_name and "polygon" in transform_name:
                    # additional check:
                    try:
                        if dataStorage.project.crs().isGeographic():
                            # logToUser("Extrusion can only be applied when project CRS is using metric units", level = 1, func = inspect.stack()[0][3])
                            return None
                    except:
                        return None

                    try:
                        existing_height = float(feature[attribute])
                        if (
                            existing_height is None or str(feature[attribute]) == "NULL"
                        ):  # if attribute value invalid
                            if ignore is True:
                                return None
                            else:  # find approximate value
                                all_existing_vals = [
                                    f[attribute]
                                    for f in layer.getFeatures()
                                    if (
                                        f[attribute] is not None
                                        and (
                                            isinstance(f[attribute], float)
                                            or isinstance(f[attribute], int)
                                        )
                                    )
                                ]
                                try:
                                    if len(all_existing_vals) > 5:
                                        height_average = all_existing_vals[
                                            int(len(all_existing_vals) / 2)
                                        ]
                                        height = random.randint(
                                            height_average - 5, height_average + 5
                                        )
                                    else:
                                        height = random.randint(10, 20)
                                except:
                                    height = random.randint(10, 20)
                        else:  # if acceptable value: reading from existing attribute
                            height = existing_height

                    except:  # if no Height attribute
                        if ignore is True:
                            height = None
                        else:
                            height = random.randint(10, 20)

    return height


def specklePolycurveToPoints(poly: Polycurve, dataStorage) -> List[Point]:
    # print("_____Speckle Polycurve to points____")
    try:
        points = []
        for i, segm in enumerate(poly.segments):
            pts = []
            if isinstance(segm, Arc) or isinstance(
                segm, Circle
            ):  # or isinstance(segm, Curve):
                pts: List[Point] = speckleArcCircleToPoints(segm)
            elif isinstance(segm, Line):
                pts: List[Point] = [segm.start, segm.end]
            elif isinstance(segm, Polyline):
                pts: List[Point] = segm.as_points()

            if i == 0:
                points.extend(pts)
            else:
                points.extend(pts[1:])
        return points
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return


def speckleArcCircleToPoints(poly: Union[Arc, Circle], dataStorage) -> List[Point]:
    try:
        # print("__Arc or Circle to Points___")
        points = []
        # print(poly.plane)
        # print(poly.plane.normal)
        if poly.plane is None or poly.plane.normal.z == 0:
            normal = 1
        else:
            normal = poly.plane.normal.z

        if isinstance(poly, Circle):
            interval = 2 * math.pi
            range_start = 0
            angle1 = 0

        else:  # if Arc
            points.append(poly.startPoint)
            range_start = 0

            # angle1, angle2 = getArcAngles(poly)
            interval, angle1, angle2 = getArcRadianAngle(poly, dataStorage)

            if (angle1 > angle2 and normal == -1) or (angle2 > angle1 and normal == 1):
                pass
            if angle1 > angle2 and normal == 1:
                interval = abs((2 * math.pi - angle1) + angle2)
            if angle2 > angle1 and normal == -1:
                interval = abs((2 * math.pi - angle2) + angle1)

        pointsNum = math.floor(abs(interval)) * 12
        if pointsNum < 4:
            pointsNum = 4

        for i in range(range_start, pointsNum + 1):
            k = i / pointsNum  # to reset values from 1/10 to 1
            angle = angle1 + k * interval * normal

            pt = Point(
                x=poly.plane.origin.x + poly.radius * cos(angle),
                y=poly.plane.origin.y + poly.radius * sin(angle),
                z=0,
            )

            pt.units = poly.plane.origin.units
            points.append(pt)

        if isinstance(poly, Arc):
            points.append(poly.endPoint)
        return points
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return []


def speckleBoundaryToSpecklePts(
    boundary: Union[None, Polyline, Arc, Line, Polycurve], dataStorage
) -> List[Point]:
    # add boundary points
    try:
        # print(dataStorage)
        polyBorder = []
        if isinstance(boundary, Circle) or isinstance(boundary, Arc):
            polyBorder = speckleArcCircleToPoints(boundary, dataStorage)
        elif isinstance(boundary, Polycurve):
            polyBorder = specklePolycurveToPoints(boundary, dataStorage)
        elif isinstance(boundary, Line):
            pass
        else:
            try:
                polyBorder = boundary.as_points()
            except:
                pass  # if Line or None
        for i, p in enumerate(polyBorder):
            if polyBorder[i].z == -0.0:
                polyBorder[i].z = 0
        return polyBorder
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return


def addCorrectUnits(geom, dataStorage):
    if not isinstance(geom, Base):
        return None
    units = dataStorage.currentUnits

    geom.units = units
    if isinstance(geom, Arc):
        geom.plane.origin.units = units
        geom.startPoint.units = units
        geom.midPoint.units = units
        geom.endPoint.units = units

    elif isinstance(geom, Polycurve):
        for s in geom.segments:
            s.units = units
            if isinstance(s, Arc):
                s.plane.origin.units = units
                s.startPoint.units = units
                s.midPoint.units = units
                s.endPoint.units = units

    return geom


def getArcRadianAngle(arc: Arc, dataStorage) -> List[float]:
    try:
        interval = None
        normal = arc.plane.normal.z
        angle1, angle2 = getArcAngles(arc, dataStorage)
        if angle1 is None or angle2 is None:
            return None
        interval = abs(angle2 - angle1)

        if (angle1 > angle2 and normal == -1) or (angle2 > angle1 and normal == 1):
            pass
        if angle1 > angle2 and normal == 1:
            interval = abs((2 * math.pi - angle1) + angle2)
        if angle2 > angle1 and normal == -1:
            interval = abs((2 * math.pi - angle2) + angle1)
        return interval, angle1, angle2
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return None, None, None


def getArcAngles(poly: Arc, dataStorage) -> Tuple[float]:
    try:
        if poly.startPoint.x == poly.plane.origin.x:
            angle1 = math.pi / 2
        else:
            angle1 = atan(
                abs(
                    (poly.startPoint.y - poly.plane.origin.y)
                    / (poly.startPoint.x - poly.plane.origin.x)
                )
            )  # between 0 and pi/2

        if (
            poly.plane.origin.x < poly.startPoint.x
            and poly.plane.origin.y > poly.startPoint.y
        ):
            angle1 = 2 * math.pi - angle1
        if (
            poly.plane.origin.x > poly.startPoint.x
            and poly.plane.origin.y > poly.startPoint.y
        ):
            angle1 = math.pi + angle1
        if (
            poly.plane.origin.x > poly.startPoint.x
            and poly.plane.origin.y < poly.startPoint.y
        ):
            angle1 = math.pi - angle1

        if poly.endPoint.x == poly.plane.origin.x:
            angle2 = math.pi / 2
        else:
            angle2 = atan(
                abs(
                    (poly.endPoint.y - poly.plane.origin.y)
                    / (poly.endPoint.x - poly.plane.origin.x)
                )
            )  # between 0 and pi/2

        if (
            poly.plane.origin.x < poly.endPoint.x
            and poly.plane.origin.y > poly.endPoint.y
        ):
            angle2 = 2 * math.pi - angle2
        if (
            poly.plane.origin.x > poly.endPoint.x
            and poly.plane.origin.y > poly.endPoint.y
        ):
            angle2 = math.pi + angle2
        if (
            poly.plane.origin.x > poly.endPoint.x
            and poly.plane.origin.y < poly.endPoint.y
        ):
            angle2 = math.pi - angle2

        return angle1, angle2
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return None, None


def getArcNormal(poly: Arc, midPt: Point, dataStorage):
    # print("____getArcNormal___")
    try:
        angle1, angle2 = getArcAngles(poly, dataStorage)

        if midPt.x == poly.plane.origin.x:
            angle = math.pi / 2
        else:
            angle = atan(
                abs((midPt.y - poly.plane.origin.y) / (midPt.x - poly.plane.origin.x))
            )  # between 0 and pi/2

        if poly.plane.origin.x < midPt.x and poly.plane.origin.y > midPt.y:
            angle = 2 * math.pi - angle
        if poly.plane.origin.x > midPt.x and poly.plane.origin.y > midPt.y:
            angle = math.pi + angle
        if poly.plane.origin.x > midPt.x and poly.plane.origin.y < midPt.y:
            angle = math.pi - angle

        normal = Vector()
        normal.x = normal.y = 0

        if angle1 > angle > angle2:
            normal.z = -1
        if angle1 > angle2 > angle:
            normal.z = 1

        if angle2 > angle1 > angle:
            normal.z = -1
        if angle > angle1 > angle2:
            normal.z = 1

        if angle2 > angle > angle1:
            normal.z = 1
        if angle > angle2 > angle1:
            normal.z = -1

        # print(angle1)
        # print(angle)
        # print(angle2)
        # print(normal)

        return normal
    except Exception as e:
        logToUser(e, level=2, func=inspect.stack()[0][3])
        return
