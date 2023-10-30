from datetime import datetime
from distutils.log import error
import inspect
import math
import os
import time
from tokenize import String
from typing import List
from plugin_utils.helpers import findOrCreatePath
from qgis._core import (QgsCoordinateTransform, Qgis, QgsPointXY, QgsGeometry, QgsRasterBandStats, QgsFeature, QgsFields, 
    QgsField, QgsVectorLayer, QgsRasterLayer, QgsCoordinateReferenceSystem, QgsProject,
    QgsUnitTypes )
from specklepy.objects import Base
from specklepy.objects.other import RevitParameter

from typing import Dict, Any

from PyQt5.QtCore import QVariant, QDate, QDateTime
from speckle.converter import geometry
from speckle.converter.geometry import convertToSpeckle, transform
from specklepy.objects.GIS.geometry import GisRasterElement, GisPolygonGeometry, GisNonGeometryElement, GisTopography 
from speckle.converter.geometry.mesh import constructMesh, constructMeshFromRaster
from specklepy.objects.GIS.layers import RasterLayer
from specklepy.objects.geometry import Mesh
from speckle.converter.geometry.point import applyOffsetsRotation
#from speckle.utils.panel_logging import logger
from speckle.converter.layers.utils import get_raster_stats, get_scale_factor_to_meter, getArrayIndicesFromXY, getElevationLayer, getHeightWithRemainderFromArray, getRasterArrays, getVariantFromValue, getXYofArrayPoint, isAppliedLayerTransformByKeywords, traverseDict, validateAttributeName 
from osgeo import (  # # C:\Program Files\QGIS 3.20.2\apps\Python39\Lib\site-packages\osgeo
    gdal, osr)
import numpy as np 
import scipy as sp
import scipy.ndimage

from speckle.utils.panel_logging import logToUser

def featureToSpeckle(fieldnames: List[str], f: QgsFeature, geomType, sourceCRS: QgsCoordinateReferenceSystem, targetCRS: QgsCoordinateReferenceSystem, project: QgsProject, selectedLayer: QgsVectorLayer or QgsRasterLayer, dataStorage):
    #print("Feature to Speckle")
    #print(dataStorage)
    if dataStorage is None: return 
    units = dataStorage.currentUnits
    new_report = {"obj_type": "", "errors": ""}
    iterations = 0
    try:
        geom = None
        
        if geomType == "None":
            geom = GisNonGeometryElement()
            new_report = {"obj_type": geom.speckle_type, "errors": ""}
        else: 
            #apply transformation if needed
            if sourceCRS != targetCRS:
                xform = QgsCoordinateTransform(sourceCRS, targetCRS, project)
                geometry = f.geometry()
                geometry.transform(xform)
                f.setGeometry(geometry)
            
            # Try to extract geometry
            skipped_msg = "Feature skipped due to invalid geometry"
            try:
                geom, iterations = convertToSpeckle(f, selectedLayer, dataStorage)
                if geom is not None and geom!="None": 
                    if not isinstance(geom.geometry, List):
                        logToUser("Geometry not in list format", level = 2, func = inspect.stack()[0][3])
                        return None 

                    all_errors = ""
                    for g in geom.geometry:
                        if g is None or g=="None": 
                            all_errors += skipped_msg + ", "
                            logToUser(skipped_msg, level = 2, func = inspect.stack()[0][3])
                        elif isinstance(g, GisPolygonGeometry): 
                            if len(g.displayValue) == 0:
                                all_errors += "Polygon sent, but display mesh not generated" + ", "
                                logToUser("Polygon sent, but display mesh not generated", level = 1, func = inspect.stack()[0][3])
                            elif iterations is not None and iterations > 0:
                                all_errors += "Polygon display mesh is simplified" + ", "
                                logToUser("Polygon display mesh is simplified", level = 1, func = inspect.stack()[0][3])

                    if len(geom.geometry) == 0:
                        all_errors = "No geometry converted"
                    new_report.update({"obj_type": geom.speckle_type, "errors": all_errors})
                                
                else: # geom is None
                    new_report = {"obj_type": "", "errors": skipped_msg}
                    logToUser(skipped_msg, level = 2, func = inspect.stack()[0][3])
                    geom = GisNonGeometryElement()
            except Exception as error:
                new_report = {"obj_type": "", "errors": "Error converting geometry: " + str(error)}
                logToUser("Error converting geometry: " + str(error), level = 2, func = inspect.stack()[0][3])

        attributes = Base()
        for name in fieldnames: 
            corrected = validateAttributeName(name, fieldnames)
            f_val = f[name]
            if f_val == "NULL" or f_val is None or str(f_val) == "NULL": f_val = None
            if isinstance(f[name], list): 
                x = ""
                for i, attr in enumerate(f[name]): 
                    if i==0: x += str(attr)
                    else: x += ", " + str(attr)
                f_val = x 
            attributes[corrected] = f_val

        #if geom is not None and geom!="None":
        geom.attributes = attributes
        
        dataStorage.latestActionFeaturesReport[len(dataStorage.latestActionFeaturesReport)-1].update(new_report)
        return geom
    
    except Exception as e:
        new_report.update({"errors": e})
        dataStorage.latestActionFeaturesReport[len(dataStorage.latestActionFeaturesReport)-1].update(new_report)
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return geom
          
def bimFeatureToNative(exist_feat: QgsFeature, feature: Base, fields: QgsFields, crs, path: str, dataStorage):
    #print("04_________BIM Feature To Native____________")
    try:
        exist_feat.setFields(fields)  

        feat_updated = updateFeat(exist_feat, fields, feature)
        #print(fields.toList())
        #print(feature)
        #print(feat_updated)

        return feat_updated
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return 

def addFeatVariant(key, variant, value, f: QgsFeature):
    #print("__________add variant")
    try:
        feat = f
        
        r'''
        if isinstance(value, str) and variant == QVariant.Date:  # 14
            y,m,d = value.split("(")[1].split(")")[0].split(",")[:3]
            value = QDate(int(y), int(m), int(d) ) 
        elif isinstance(value, str) and variant == QVariant.DateTime: 
            y,m,d,t1,t2 = value.split("(")[1].split(")")[0].split(",")[:5]
            value = QDateTime(int(y), int(m), int(d), int(t1), int(t2) )
        '''
        if variant == 10: value = str(value) # string

        if value != "NULL" and value != "None":
            if variant == getVariantFromValue(value): 
                feat[key] = value
            elif isinstance(value, float) and variant == 4: #float, but expecting Long (integer)
                feat[key] = int(value) 
            elif isinstance(value, int) and variant == 6: #int (longlong), but expecting float 
                feat[key] = float(value) 
            else: 
                feat[key] = None 
                #print(key); print(value); print(type(value)); print(variant); print(getVariantFromValue(value))
        elif isinstance(variant, int): feat[key] = None
        return feat 
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return 

def updateFeat(feat: QgsFeature, fields: QgsFields, feature: Base) -> dict[str, Any]:
    try:
        #print("__updateFeat")
        for i, key in enumerate(fields.names()): 
            variant = fields.at(i).type()
            try:
                if key == "Speckle_ID": 
                    value = str(feature["id"])
                    #if key != "parameters": print(value)
                    feat[key] = value 

                    feat = addFeatVariant(key, variant, value, feat)

                else:
                    try: 
                        value = feature[key] 
                        feat = addFeatVariant(key, variant, value, feat)

                    except:
                        value = None
                        rootName = key.split("_")[0]
                        #try: # if the root category exists
                        # if its'a list 
                        if isinstance(feature[rootName], list):
                            for i in range(len(feature[rootName])):
                                try:
                                    newF, newVals = traverseDict({}, {}, rootName + "_" + str(i), feature[rootName][i])
                                    for i, (key,value) in enumerate(newVals.items()):
                                        for k, (x,y) in enumerate(newF.items()):
                                            if key == x: variant = y; break
                                        feat = addFeatVariant(key, variant, value, feat)
                                except Exception as e: print(e)
                        #except: # if not a list
                        else:
                            try:
                                newF, newVals = traverseDict({}, {}, rootName, feature[rootName])
                                for i, (key,value) in enumerate(newVals.items()):
                                    for k, (x,y) in enumerate(newF.items()):
                                        if key == x: variant = y; break
                                    feat = addFeatVariant(key, variant, value, feat)
                            except Exception as e: feat.update({key: None})
            except Exception as e: 
                feat[key] = None
        #feat_sorted = {k: v for k, v in sorted(feat.items(), key=lambda item: item[0])}
        #print("_________________end of updating a feature_________________________")
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])

    return feat 


def rasterFeatureToSpeckle(selectedLayer: QgsRasterLayer, projectCRS:QgsCoordinateReferenceSystem, project: QgsProject, plugin ) -> Base:
    
    dataStorage = plugin.dataStorage
    if dataStorage is None: return

    b = GisRasterElement(units = dataStorage.currentUnits)
    try:
        terrain_transform = False
        texture_transform = False
        #height_list = rasterBandVals[0]          
        terrain_transform = isAppliedLayerTransformByKeywords(selectedLayer, ["elevation", "mesh"], ["texture"], dataStorage)
        texture_transform = isAppliedLayerTransformByKeywords(selectedLayer, ["texture"], [], dataStorage)
        if terrain_transform is True or texture_transform is True:
            b = GisTopography(units = dataStorage.currentUnits)


        rasterBandCount = selectedLayer.bandCount()
        rasterBandNames = []
        rasterDimensions = [selectedLayer.width(), selectedLayer.height()]
        #if rasterDimensions[0]*rasterDimensions[1] > 1000000 :
        #   logToUser("Large layer: ", level = 1, func = inspect.stack()[0][3])

        ds = gdal.Open(selectedLayer.source(), gdal.GA_ReadOnly)
        if ds is None:
            return None

        originX = ds.GetGeoTransform()[0]
        originY = ds.GetGeoTransform()[3]
        rasterOriginPoint = QgsPointXY(originX, originY)
        rasterResXY = [float(ds.GetGeoTransform()[1]), float(ds.GetGeoTransform()[5])]
        rasterWkt = ds.GetProjection() 
        rasterProj = QgsCoordinateReferenceSystem.fromWkt(rasterWkt).toProj().replace(" +type=crs","")
        rasterBandNoDataVal = []
        rasterBandMinVal = []
        rasterBandMaxVal = []
        rasterBandVals = []

        # Try to extract geometry
        reprojectedPt = QgsGeometry.fromPointXY(QgsPointXY())
        try:
            reprojectedPt = rasterOriginPoint
            if selectedLayer.crs()!= projectCRS: 
                reprojectedPt = transform.transform(project, rasterOriginPoint, selectedLayer.crs(), projectCRS)
        except Exception as error:
            #logToUser("Error converting point geometry: " + str(error), level = 2, func = inspect.stack()[0][3])
            logToUser("Error converting point geometry: " + str(error), level = 2)
        
        for index in range(rasterBandCount):
            rasterBandNames.append(selectedLayer.bandName(index+1))
            rb = ds.GetRasterBand(index+1)
            valMin = selectedLayer.dataProvider().bandStatistics(index+1, QgsRasterBandStats.All).minimumValue
            valMax = selectedLayer.dataProvider().bandStatistics(index+1, QgsRasterBandStats.All).maximumValue
            bandVals = rb.ReadAsArray().tolist()

            bandValsFlat = []
            [bandValsFlat.extend(item) for item in bandVals]
            #look at mesh chunking

            const = float(-1* math.pow(10,30))
            defaultNoData = rb.GetNoDataValue()
            #print(type(rb.GetNoDataValue()))

            # check whether NA value is too small or raster has too small values
            # assign min value of an actual list; re-assign NA val; replace list items to new NA val
            try:
                # create "safe" fake NA value; replace extreme values with it
                fakeNA = max(bandValsFlat) + 1 
                bandValsFlatFake = [fakeNA if val<=const else val for val in bandValsFlat] # replace all values corresponding to NoData value 
                
                #if default NA value is too small
                if (isinstance(defaultNoData, float) or isinstance(defaultNoData, int)) and defaultNoData < const:
                    # find and rewrite min of actual band values; create new NA value
                    valMin = min(bandValsFlatFake)
                    noDataValNew = valMin - 1000 # use new adequate value
                    rasterBandNoDataVal.append(noDataValNew)
                    # replace fake NA with new NA
                    bandValsFlat = [noDataValNew if val == fakeNA else val for val in bandValsFlatFake] # replace all values corresponding to NoData value 
                
                # if default val unaccessible and minimum val is too small 
                elif (isinstance(defaultNoData, str) or defaultNoData is None) and valMin < const: # if there are extremely small values but default NA unaccessible 
                    noDataValNew = valMin 
                    rasterBandNoDataVal.append(noDataValNew)
                    # replace fake NA with new NA
                    bandValsFlat = [noDataValNew if val == fakeNA else val for val in bandValsFlatFake] # replace all values corresponding to NoData value 
                    # last, change minValto actual one
                    valMin = min(bandValsFlatFake)

                else: rasterBandNoDataVal.append(rb.GetNoDataValue())

            except: rasterBandNoDataVal.append(rb.GetNoDataValue())

            
            rasterBandVals.append(bandValsFlat)
            rasterBandMinVal.append(valMin)
            rasterBandMaxVal.append(valMax)
            b["@(10000)" + selectedLayer.bandName(index+1) + "_values"] = bandValsFlat #[0:int(max_values/rasterBandCount)]

        b.x_resolution = rasterResXY[0]
        b.y_resolution = rasterResXY[1]
        b.x_size = rasterDimensions[0]
        b.y_size = rasterDimensions[1]
        b.x_origin, b.y_origin = applyOffsetsRotation(reprojectedPt.x(), reprojectedPt.y() , dataStorage)
        b.band_count = rasterBandCount
        b.band_names = rasterBandNames
        b.noDataValue = rasterBandNoDataVal
        # creating a mesh
        count = 0
        rendererType = selectedLayer.renderer().type()

        xy_list = []
        z_list = []
        #print(rendererType)
        # identify symbology type and if Multiband, which band is which color

        ############################################################# 
        
        elevationLayer = None 
        elevationProj = None 
        if texture_transform is True:
            elevationLayer = getElevationLayer(dataStorage) 
        elif terrain_transform is True:
            elevationLayer = selectedLayer
        
        if elevationLayer is not None:
            settings_elevation_layer = get_raster_stats(elevationLayer)
            elevationResX, elevationResY, elevationOriginX, elevationOriginY, elevationSizeX, elevationSizeY, elevationWkt, elevationProj = settings_elevation_layer
            
            # reproject the elevation layer 
            if elevationProj is not None and rasterProj is not None and elevationProj != rasterProj:
                try: 
                    #print("reproject elevation layer")
                    #print(elevationLayer.source())
                    #print(elevationLayer.crs().authid())
                    p = os.path.expandvars(r'%LOCALAPPDATA%') + "\\Temp\\Speckle_QGIS_temp\\" + datetime.now().strftime("%Y-%m-%d_%H-%M")
                    findOrCreatePath(p)
                    path = p
                    out = p + "\\out.tif"
                    gdal.Warp(out, elevationLayer.source(), dstSRS = selectedLayer.crs().authid(), xRes = elevationResX, yRes = elevationResY ) 
                    
                    elevationLayer = QgsRasterLayer(out, '', 'gdal')
                    settings_elevation_layer = get_raster_stats(elevationLayer)
                    elevationResX, elevationResY, elevationOriginX, elevationOriginY, elevationSizeX, elevationSizeY, elevationWkt, elevationProj = settings_elevation_layer
                except Exception as e:
                    logToUser(f"Reprojection did not succeed: {e}", level = 0)
            elevation_arrays, all_mins, all_maxs, all_na = getRasterArrays(elevationLayer)
            array_band = elevation_arrays[0]

            height_array = np.where( (array_band < const) | (array_band > -1*const) | (array_band == all_na[0]), np.nan, array_band)
            try:
                height_array = height_array.astype(float)
            except:
                try: 
                    arr = []
                    for row in height_array:
                        new_row = []
                        for item in row:
                            try: 
                                new_row.append(float(item))
                            except:
                                new_row.append(np.nan)
                        arr.append(new_row)
                    height_array = np.array(arr).astype(float)
                except:
                    height_array = height_array[[isinstance(i, float) for i in height_array]] 
        else:
            elevation_arrays = all_mins = all_maxs = all_na = None
            elevationResX = elevationResY = elevationOriginX = elevationOriginY = elevationSizeX = elevationSizeY = elevationWkt = None
            height_array = None
        
        largeTransform = False
        if texture_transform is True and elevationLayer is None:
            logToUser(f"Elevation layer is not found. Texture transformation for layer '{selectedLayer.name()}' will not be applied", level = 1, plugin = plugin.dockwidget)
        elif texture_transform is True and rasterDimensions[1]*rasterDimensions[0]>=10000 and elevationProj is not None and rasterProj is not None and elevationProj != rasterProj:
            # warning if >= 100x100 raster is being projected to an elevation with different CRS 
            logToUser(f"Texture transformation for the layer '{selectedLayer.name()}' might take a while 🕒\nTip: reproject one of the layers (texture or elevation) to the other layer's CRS. When both layers have the same CRS, texture transformation will be much faster.", level = 0, plugin = plugin.dockwidget)
            largeTransform  = True
        elif texture_transform is True and rasterDimensions[1]*rasterDimensions[0]>=250000:
            # warning if >= 500x500 raster is being projected to any elevation 
            logToUser(f"Texture transformation for the layer '{selectedLayer.name()}' might take a while 🕒", level = 0, plugin = plugin.dockwidget)
            largeTransform = True 
        ############################################################
        faces_array = []
        colors_array = []
        vertices_array = []
        array_z = [] # size is large by 1 than the raster size, in both dimensions 
        for v in range(rasterDimensions[1] ): #each row, Y
            if largeTransform is True:
                if v == int(rasterDimensions[1]/20): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 5%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]/10): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 10%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]/5): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 20%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]*2/5): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 40%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]*3/5): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 60%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]*4/5): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 80%...", level = 0, plugin = plugin.dockwidget)
                elif v == int(rasterDimensions[1]*9/10): 
                    logToUser(f"Converting layer '{selectedLayer.name()}': 90%...", level = 0, plugin = plugin.dockwidget)
            vertices = []
            faces = []
            colors = []
            row_z = []
            row_z_bottom = []
            for h in range(rasterDimensions[0] ): #item in a row, X
                pt1 = QgsPointXY(rasterOriginPoint.x()+h*rasterResXY[0], rasterOriginPoint.y()+v*rasterResXY[1])
                pt2 = QgsPointXY(rasterOriginPoint.x()+h*rasterResXY[0], rasterOriginPoint.y()+(v+1)*rasterResXY[1])
                pt3 = QgsPointXY(rasterOriginPoint.x()+(h+1)*rasterResXY[0], rasterOriginPoint.y()+(v+1)*rasterResXY[1])
                pt4 = QgsPointXY(rasterOriginPoint.x()+(h+1)*rasterResXY[0], rasterOriginPoint.y()+v*rasterResXY[1])
                # first, get point coordinates with correct position and resolution, then reproject each:
                if selectedLayer.crs()!= projectCRS:
                    pt1 = transform.transform(project, src = pt1, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                    pt2 = transform.transform(project, src = pt2, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                    pt3 = transform.transform(project, src = pt3, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                    pt4 = transform.transform(project, src = pt4, crsSrc = selectedLayer.crs(), crsDest = projectCRS)
                
                z1 = z2 = z3 = z4 = 0
                index1 = index1_0 = None
        
                ############################################################# 
                if (terrain_transform is True or texture_transform is True) and height_array is not None:
                    if texture_transform is True: # texture 
                        # index1: index on y-scale 
                        posX, posY = getXYofArrayPoint((rasterResXY[0], rasterResXY[1], originX, originY, rasterDimensions[1], rasterDimensions[0], rasterWkt, rasterProj), h, v, elevationWkt, elevationProj)
                        index1, index2, remainder1, remainder2 = getArrayIndicesFromXY((elevationResX, elevationResY, elevationOriginX, elevationOriginY, elevationSizeX, elevationSizeY, elevationWkt, elevationProj), posX, posY )
                        index1_0, index2_0, remainder1_0, remainder2_0 = getArrayIndicesFromXY((elevationResX, elevationResY, elevationOriginX, elevationOriginY, elevationSizeX, elevationSizeY, elevationWkt, elevationProj), posX-rasterResXY[0], posY-rasterResXY[1] )
                    else: # elevation 
                        index1 = v
                        index1_0 = v-1
                        index2 = h
                        index2_0 = h-1

                    if index1 is None or index1_0 is None: 
                        #count += 4
                        #continue # skip the pixel
                        z1 = z2 = z3 = z4 = np.nan 
                    else: 
                        # top vertices ######################################
                        try:
                            z1 = z_list[ xy_list.index((pt1.x(), pt1.y())) ]
                        except:
                            if index1>0 and index2>0:
                                z1 = getHeightWithRemainderFromArray(height_array, texture_transform, index1_0, index2_0)
                            elif index1>0:
                                z1 = getHeightWithRemainderFromArray(height_array, texture_transform, index1_0, index2)
                            elif index2>0:
                                z1 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2_0)
                            else:
                                z1 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2)
                            
                            if z1 is not None: 
                                z_list.append(z1)
                                xy_list.append((pt1.x(), pt1.y()))
                            
                        #################### z4 
                        try:
                            z4 = z_list[ xy_list.index((pt4.x(), pt4.y())) ]
                        except:
                            if index1>0:
                                z4 = getHeightWithRemainderFromArray(height_array, texture_transform, index1_0, index2)
                            else:
                                z4 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2)
                        
                            if z4 is not None: 
                                z_list.append(z4)
                                xy_list.append((pt4.x(), pt4.y()))

                        # bottom vertices ######################################
                        z3 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2)
                        if z3 is not None: 
                            z_list.append(z3)
                            xy_list.append((pt3.x(), pt3.y()))

                        try:
                            z2 = z_list[ xy_list.index((pt2.x(), pt2.y())) ]
                        except:
                            if index2>0:
                                z2 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2_0)
                            else: 
                                z2 = getHeightWithRemainderFromArray(height_array, texture_transform, index1, index2)
                            if z2 is not None: 
                                z_list.append(z2)
                                xy_list.append((pt2.x(), pt2.y()))
                        
                        ##############################################
                    
                    max_len = rasterDimensions[0]*4 + 4
                    if len(z_list) > max_len:
                        z_list = z_list[len(z_list)-max_len:]
                        xy_list = xy_list[len(xy_list)-max_len:]
                    
                    ### list to smoothen later: 
                    if h==0: 
                        row_z.append(z1)
                        row_z_bottom.append(z2)
                    row_z.append(z4)
                    row_z_bottom.append(z3)

                ########################################################
                x1, y1 = applyOffsetsRotation(pt1.x(), pt1.y(), dataStorage)
                x2, y2 = applyOffsetsRotation(pt2.x(), pt2.y(), dataStorage)
                x3, y3 = applyOffsetsRotation(pt3.x(), pt3.y(), dataStorage)
                x4, y4 = applyOffsetsRotation(pt4.x(), pt4.y(), dataStorage)

                vertices.append([x1, y1, z1, x2, y2, z2, x3, y3, z3, x4, y4, z4]) ## add 4 points
                current_vertices = v*rasterDimensions[0]*4 + h*4 #len(np.array(faces_array).flatten()) * 4 / 5
                faces.append([4, current_vertices, current_vertices + 1, current_vertices + 2, current_vertices + 3])

                # color vertices according to QGIS renderer
                color = (255<<24) + (0<<16) + (0<<8) + 0
                noValColor = selectedLayer.renderer().nodataColor().getRgb() 

                colorLayer = selectedLayer
                currentRasterBandCount = rasterBandCount

                if (terrain_transform is True or texture_transform is True) and height_array is not None and (index1 is None or index1_0 is None): # transparent color
                    color = (0<<24) + (0<<16) + (0<<8) + 0
                elif rendererType == "multibandcolor": 
                    valR = 0
                    valG = 0
                    valB = 0
                    bandRed = int(colorLayer.renderer().redBand())
                    bandGreen = int(colorLayer.renderer().greenBand())
                    bandBlue = int(colorLayer.renderer().blueBand())

                    alpha = 255
                    for k in range(currentRasterBandCount): 

                        valRange = (rasterBandMaxVal[k] - rasterBandMinVal[k])
                        if valRange == 0: colorVal = 0
                        elif rasterBandVals[k][int(count/4)] == rasterBandNoDataVal[k]: 
                            colorVal = 0
                        #    alpha = 0
                        #   break
                        else: colorVal = int( (rasterBandVals[k][int(count/4)] - rasterBandMinVal[k]) / valRange * 255 )
                            
                        if k+1 == bandRed: valR = colorVal
                        if k+1 == bandGreen: valG = colorVal
                        if k+1 == bandBlue: valB = colorVal

                    color =  (alpha<<24) + (valR<<16) + (valG<<8) + valB 

                elif rendererType == "paletted":
                    bandIndex = colorLayer.renderer().band()-1 #int
                    #if textureLayer is not None:
                    #    value = texture_arrays[bandIndex][index1][index2] 
                    #else:
                    value = rasterBandVals[bandIndex][int(count/4)] #find in the list and match with color

                    rendererClasses = colorLayer.renderer().classes()
                    for c in range(len(rendererClasses)-1):
                        if value >= rendererClasses[c].value and value <= rendererClasses[c+1].value :
                            rgb = rendererClasses[c].color.getRgb()
                            color =  (255<<24) + (rgb[0]<<16) + (rgb[1]<<8) + rgb[2]
                            break

                elif rendererType == "singlebandpseudocolor":
                    bandIndex = colorLayer.renderer().band()-1 #int
                    #if textureLayer is not None:
                    #    value = texture_arrays[bandIndex][index1][index2] 
                    #else:
                    value = rasterBandVals[bandIndex][int(count/4)] #find in the list and match with color

                    rendererClasses = colorLayer.renderer().legendSymbologyItems()
                    for c in range(len(rendererClasses)-1):
                        if value >= float(rendererClasses[c][0]) and value <= float(rendererClasses[c+1][0]) :
                            rgb = rendererClasses[c][1].getRgb()
                            color =  (255<<24) + (rgb[0]<<16) + (rgb[1]<<8) + rgb[2]
                            break

                else:
                    if rendererType == "singlebandgray":
                        bandIndex = colorLayer.renderer().grayBand()-1
                    if rendererType == "hillshade":
                        bandIndex = colorLayer.renderer().band()-1
                    if rendererType == "contour":
                        try: bandIndex = colorLayer.renderer().inputBand()-1
                        except:
                            try: bandIndex = colorLayer.renderer().band()-1
                            except: bandIndex = 0
                    else: # e.g. single band data
                        bandIndex = 0
                    
                    if rasterBandVals[bandIndex][int(count/4)] >= rasterBandMinVal[bandIndex]: 
                        # REMAP band values to (0,255) range
                        valRange = (rasterBandMaxVal[bandIndex] - rasterBandMinVal[bandIndex])
                        if valRange == 0: colorVal = 0
                        else: colorVal = int( (rasterBandVals[bandIndex][int(count/4)] - rasterBandMinVal[bandIndex]) / valRange * 255 )
                        color =  (255<<24) + (colorVal<<16) + (colorVal<<8) + colorVal

                colors.append([color,color,color,color])
                count += 4

            # after each row
            vertices_array.append(vertices)
            faces_array.append(faces)
            colors_array.append(colors)

            if v == 0: array_z.append(row_z)
            array_z.append(row_z_bottom)
        
        # after the entire loop
        faces_filtered = []
        colors_filtered = []
        vertices_filtered = []

        ## end of the the table
        smooth = False
        if terrain_transform is True or texture_transform is True:
            smooth = True
        if smooth is True and len(row_z)>2 and len(array_z)>2:
            array_z_nans = np.array(array_z)

            array_z_filled = np.array(array_z)
            mask = np.isnan(array_z_filled)
            array_z_filled[mask] = np.interp(np.flatnonzero(mask), np.flatnonzero(~mask), array_z_filled[~mask])

            sigma = 0.8 # for elevation
            if texture_transform is True:
                sigma = 1 # for texture

                # increase sigma if needed
                try:
                    unitsRaster = QgsUnitTypes.encodeUnit(selectedLayer.crs().mapUnits())
                    unitsElevation = QgsUnitTypes.encodeUnit(elevationLayer.crs().mapUnits())
                    #print(unitsRaster)
                    #print(unitsElevation)
                    resRasterX = get_scale_factor_to_meter(unitsRaster) * rasterResXY[0] 
                    resElevX = get_scale_factor_to_meter(unitsElevation) * elevationResX 
                    #print(resRasterX)
                    #print(resElevX)
                    if resRasterX/resElevX >=2 or resElevX/resRasterX >=2:
                        sigma = math.sqrt(max(resRasterX/resElevX, resElevX/resRasterX))
                        #print(sigma)
                except: pass 

            gaussian_array = sp.ndimage.filters.gaussian_filter(array_z_filled, sigma, mode='nearest')

            for v in range(rasterDimensions[1] ): #each row, Y
                for h in range(rasterDimensions[0] ): #item in a row, X
                    if not np.isnan(array_z_nans[v][h]):

                        vertices_item = vertices_array[v][h]
                        #print(vertices_item)
                        vertices_item[2] = gaussian_array[v][h]
                        vertices_item[5] = gaussian_array[v+1][h]
                        vertices_item[8] = gaussian_array[v+1][h+1]
                        vertices_item[11] = gaussian_array[v][h+1]
                        vertices_filtered.extend(vertices_item) 
                        
                        currentFaces = len(faces_filtered)/5 *4
                        faces_filtered.extend([4, currentFaces,currentFaces+1,currentFaces+2,currentFaces+3])
                        #print(faces_filtered)
                        colors_filtered.extend(colors_array[v][h])
                        #print(colors_array[v][h])
        else:
            faces_filtered = np.array(faces_array).flatten().tolist()
            colors_filtered = np.array(colors_array).flatten().tolist()
            vertices_filtered = np.array(vertices_array).flatten().tolist()
        
        #if len(colors)/4*5 == len(faces) and len(colors)*3 == len(vertices):
        mesh = constructMeshFromRaster(vertices_filtered, faces_filtered, colors_filtered, dataStorage)
        if mesh is not None: 
            mesh.units = dataStorage.currentUnits
            b.displayValue = [ mesh ]
        else: 
            logToUser("Something went wrong. Mesh cannot be created, only raster data will be sent. ", level = 2, plugin = plugin.dockwidget)

        return b

    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return None 
        
def trianglateQuadMesh(mesh: Mesh) -> Mesh:
    new_mesh = None
    try:
        new_v: List[float] = []
        new_f: List[int] = []
        new_c: List[int] = []

        # new list with face indices 
        r'''
        temp_f = []
        used_ind = []
        for i, f in enumerate(mesh.faces):
            try:
                if i%5 != 0 and i not in used_ind: #ignore indices and used pts
                    temp_f.extend([mesh.faces[i], mesh.faces[i+1], mesh.faces[i+2], mesh.faces[i+2], mesh.faces[i+3], mesh.faces[i]])
                    used_ind.extend([i,i+1,i+2,i+3])
            except Exception as e: print(e) 
        for i, f in enumerate(temp_f):
            if i%3 == 0: new_f.append(int(3))
            new_f.append(int(f))
        '''
        
        # fill new color and vertices lists 
        used_ind = []
        for i, c in enumerate(mesh.colors):
            try:
                #new_c.append(c)
                #continue
                if i not in used_ind:
                    new_c.extend([mesh.colors[i],mesh.colors[i+1],mesh.colors[i+2],mesh.colors[i+2],mesh.colors[i+3],mesh.colors[i]])
                    used_ind.extend([i,i+1,i+2,i+3])
            except Exception as e: print(e) 
                
        used_ind = []
        for i, v in enumerate(mesh.vertices):
            try:
                #new_v.append(v)
                #continue
                if i not in used_ind:
                    v0 = [mesh.vertices[i],mesh.vertices[i+1],mesh.vertices[i+2]]
                    v1 = [mesh.vertices[i+3],mesh.vertices[i+4],mesh.vertices[i+5]]
                    v2 = [mesh.vertices[i+6],mesh.vertices[i+7],mesh.vertices[i+8]]
                    v3 = [mesh.vertices[i+9],mesh.vertices[i+10],mesh.vertices[i+11]]
                    
                    new_v.extend( v0+v1+v2+v2+v3+v0 )
                    new_f.extend([int(3), int(i/12), int(i/12)+1, int(i/12)+2, int(3), int(i/12)+3, int(i/12)+4, int(i/12)+5 ])
                    used_ind.extend(list(range(i, i+12)))
            except Exception as e: print(e) 
        #print(len(new_v))
        #print(len(new_f))
        #print(len(new_c))
        new_mesh = Mesh.create(new_v, new_f, new_c)
        new_mesh.units = mesh.units
    except Exception as e:
        print(e)
        pass
    return new_mesh

def featureToNative(feature: Base, fields: QgsFields, dataStorage):
    feat = QgsFeature()
    #print("___featureToNative")
    try:
        qgsGeom = None 

        if isinstance(feature, GisNonGeometryElement): pass
        else: 
            try: 
                speckle_geom = feature.geometry # for QGIS / ArcGIS Layer type from 2.14
            except:
                try: speckle_geom = feature["geometry"] # for QGIS / ArcGIS Layer type before 2.14
                except:  speckle_geom = feature # for created in other software

            if not isinstance(speckle_geom, list):
                qgsGeom = geometry.convertToNative(speckle_geom, dataStorage)
            
            elif isinstance(speckle_geom, list):
                if len(speckle_geom)==1:
                    qgsGeom = geometry.convertToNative(speckle_geom[0], dataStorage)
                elif len(speckle_geom)>1: 
                    qgsGeom = geometry.convertToNativeMulti(speckle_geom, dataStorage)
                else: 
                    logToUser(f"Feature '{feature.id}' does not contain geometry", level = 2, func = inspect.stack()[0][3])

            if qgsGeom is not None: 
                feat.setGeometry(qgsGeom)
            else: return None 

        feat.setFields(fields)  
        for field in fields:
            name = str(field.name())
            variant = field.type()
            #if name == "id": feat[name] = str(feature["applicationId"])

            try: 
                value = feature.attributes[name] # fro 2.14 onwards 
            except: 
                try: 
                    value = feature[name]
                except: 
                    if name == "Speckle_ID": 
                        try: 
                            value = str(feature["Speckle_ID"]) # if GIS already generated this field
                        except:
                            try: value = str(feature["speckle_id"]) 
                            except: value = str(feature["id"])
                    else: 
                        value = None 
                        #logger.logToUser(f"Field {name} not found", Qgis.Warning)
                        #return None
            
            if variant == QVariant.String: value = str(value) 
            
            if isinstance(value, str) and variant == QVariant.Date:  # 14
                y,m,d = value.split("(")[1].split(")")[0].split(",")[:3]
                value = QDate(int(y), int(m), int(d) ) 
            elif isinstance(value, str) and variant == QVariant.DateTime: 
                y,m,d,t1,t2 = value.split("(")[1].split(")")[0].split(",")[:5]
                value = QDateTime(int(y), int(m), int(d), int(t1), int(t2) )
            
            if variant == getVariantFromValue(value) and value != "NULL" and value != "None": 
                feat[name] = value
            
        return feat
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return feat

def nonGeomFeatureToNative(feature: Base, fields: QgsFields, dataStorage):
    try:
        #print("______________nonGeomFeatureToNative")
        #print(feature)
        exist_feat = QgsFeature()
        exist_feat.setFields(fields)  
        feat_updated = updateFeat(exist_feat, fields, feature)
        return feat_updated
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return 
    
def cadFeatureToNative(feature: Base, fields: QgsFields, dataStorage):
    try:
        #print("______________cadFeatureToNative")
        exist_feat = QgsFeature()
        try: speckle_geom = feature["geometry"] # for created in QGIS Layer type
        except:  speckle_geom = feature # for created in other software

        if isinstance(speckle_geom, list):
            qgsGeom = geometry.convertToNativeMulti(speckle_geom, dataStorage)
        else:
            qgsGeom = geometry.convertToNative(speckle_geom, dataStorage)

        if qgsGeom is not None: exist_feat.setGeometry(qgsGeom)
        else: return

        exist_feat.setFields(fields)  

        feat_updated = updateFeat(exist_feat, fields, feature)
        #print(fields.toList())
        #print(feature)
        #print(feat_updated)

        #### setting attributes to feature
        r'''
        for field in fields:
            #print(str(field.name()))
            name = str(field.name())
            variant = field.type()
            if name == "Speckle_ID": 
                value = str(feature["id"])
                feat[name] = value
            else: 
                # for values - normal or inside dictionaries: 
                try: value = feature[name]
                except:
                    rootName = name.split("_")[0]
                    newF, newVals = traverseDict({}, {}, rootName, feature[rootName][0])
                    for i, (k,v) in enumerate(newVals.items()):
                        if k == name: value = v; break
                # for all values: 
                if variant == QVariant.String: value = str(value) 
                
                
                if variant == getVariantFromValue(value) and value != "NULL" and value != "None": 
                    feat[name] = value
        '''       
        return feat_updated
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return 
    