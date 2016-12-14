# coding: utf-8
import cv2
import numpy as np


def _optimizeClothingMask(mask):
    """
    优化上装分割掩膜

    Args:
        mask 待优化掩膜
    Return:
        dstMask 优化后掩膜
    """
    # Step 4.1: 形态学闭操作：填充衣物mask中的洞，修复那些被误认为是背景的衣物上的图案
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Step 4.2: 形态学开操作去除衣物四周的吊饰
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)

    # Step 4.3: 填充最大轮廓，
    contours, hierachy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2:]
    if len(contours) > 0:
        maxContour = contours[0]
        for contour in contours:
            if(len(contour) > len(maxContour)):
                maxContour = contour
        cv2.drawContours(mask, [maxContour], 0, (255, 255, 255), cv2.FILLED)
    # Step 4.4: 进行一定的腐蚀操作，去除背景边界
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.erode(mask, kernel)
    return mask


def _optimizePantsMask(mask):
    """
    优化下装分割掩膜

    Args:
        mask 待优化掩膜
    Return:
        dstMask 优化后掩膜
    """
    # Step 4.1: 进行一定的腐蚀操作，去除背景边界
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.erode(mask, kernel)
    return mask


def _cutClothing(image, gray, edges):
    """
    上装分割

    Args:
        image 原图像
        gray 灰度图像
        edges 边缘灰度图像
    Return:
        mask 分割掩膜
    """
    rows, cols = edges.shape

    # Step 3.1: 人脸检测，应用grabcut圈定矩形框的时候需要去除人脸
    faceCascade = cv2.CascadeClassifier(
        "cascades/haarcascade_frontalface_default.xml")
    faces = faceCascade.detectMultiScale(gray, 1.1, 20)
    if len(faces) > 0:
        face = faces[0]
    else:
        face = None

    # Step 3.2: 查找最大外轮廓
    # cv2.findContours是原地的
    contours, hierachy = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2:]
    maxContour = contours[0]
    for contour in contours:
        if(len(contour) > len(maxContour)):
            maxContour = contour
    # 最终返回的mask
    dstMask = None
    # Step 3.3: 获得分割掩膜
    if face is None:
        # 如果不存在人脸，则填充最大外轮廓即可
        cv2.drawContours(edges, [maxContour], 0, (255, 255, 255), cv2.FILLED)
        _, dstMask = cv2.threshold(edges, 0, 255, cv2.THRESH_BINARY)
    else:
        # Step 3.3.1: 勾勒出最大外轮廓，确定区域
        cv2.drawContours(edges, [maxContour], 0, (255, 255, 255), 3)

        # Step 3.3.2: 一定程度的形态学腐蚀操作，去除衣物的粘连
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        edges = cv2.erode(edges, kernel)

        # Step 3.3.3: 均值滤波，抹除形态学操作后分散的盐噪声
        edges = cv2.medianBlur(edges, 5)

        # Step 3.3.4: 框定grabcut需要的矩形框
        # 获得最小外接矩形
        boundingRect = cv2.boundingRect(maxContour)
        # 利用多边形拟合外轮廓的形状，并获得外轮廓的凸包
        # 绘制出凸包包住拟合多边形的区域
        drawing = np.zeros((rows, cols), np.uint8)
        epsilon = 0.01 * cv2.arcLength(maxContour, True)
        approx = cv2.approxPolyDP(maxContour, epsilon, True)
        hull = cv2.convexHull(maxContour)
        cv2.drawContours(drawing, [hull], 0, (255, 255, 255), cv2.FILLED)
        cv2.drawContours(drawing, [approx], 0, (0, 0, 255), cv2.FILLED)
        # 获得这些区域的外轮廓
        contours, hierachy = cv2.findContours(
            drawing, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2:]
        # 遍历各个轮廓，获得各个轮廓的最小外接矩形
        # 进而获得最深的外接矩形，最深的外接矩形往往反映了与上装黏着的下装部分
        deepestRect = boundingRect
        for contour in contours:
            rect = cv2.boundingRect(contour)
            if rect[3] > 5:
                x, y, w, h = rect
                if y > deepestRect[1]:
                    deepestRect = rect

        # 最终用于grabcut的矩形框将排除人脸及裤装（最深矩形
        x, y, w, h = boundingRect
        y = face[1] + face[3]
        h = h - deepestRect[3] - face[3] - face[1]
        # grabcut需要的mask
        grabMask = np.zeros((rows, cols), np.uint8)
        try:
            cv2.grabCut(image, grabMask, (x, y, w, h), None,
                        None, 5, cv2.GC_INIT_WITH_RECT)
        except:
            try:
                cv2.grabCut(image, grabMask, boundingRect, None,
                        None, 5, cv2.GC_INIT_WITH_RECT)
            except:
                cv2.grabCut(image, grabMask, (20, 20, rows-40, cols-40), None,
                        None, 5, cv2.GC_INIT_WITH_RECT)
        # 将背景颜色设置为0，前景置为255
        dstMask = np.where((grabMask == 2) | (
            grabMask == 0), 0, 255).astype('uint8')
    return dstMask


def _cutPants(image, gray, edges):
    """
    下装分割

    Args:
        image 原图像
        gray 灰度图像
        edges 边缘灰度图像
    Return:
        mask 分割掩膜
    """
    rows, cols = edges.shape
    # Step 3.1: 获得最大轮廓及其外接矩形
    contours, hierachy = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2:]
    maxContour = contours[0]
    boundingRect = cv2.boundingRect(maxContour)
    grabMask = np.zeros((rows, cols), np.uint8)
    grabRect = boundingRect
    # 如果图像黏着有上装（图像轮廓没有居于中央）
    if boundingRect[1] < 20:
        # 多边形拟合
        drawing = np.zeros((rows, cols), np.uint8)
        epsilon = 0.05 * cv2.arcLength(maxContour, True)
        approx = cv2.approxPolyDP(maxContour, epsilon, True)
        hull = cv2.convexHull(maxContour)
        cv2.drawContours(drawing, [hull], 0, (255, 255, 255), cv2.FILLED)
        cv2.drawContours(drawing, [approx], 0, (0, 0, 255), cv2.FILLED)

        # 获得凸包及多边形拟合后的轮廓
        contours, hierachy = cv2.findContours(
            drawing, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2:]

        # 获得最深的外接矩形，以便排除鞋子的影响
        deepestRect = boundingRect
        for contour in contours:
            # 寻找疑似鞋子的部分
            rect = cv2.boundingRect(contour)
            if rect[3] > 100:
                x, y, w, h = rect
                if y > deepestRect[1]:
                    deepestRect = rect

        x, y, w, h = deepestRect
        y = y - 50
        grabRect = (x, y, w, h)
    try:
        cv2.grabCut(image, grabMask, grabRect, None,
                    None, 5, cv2.GC_INIT_WITH_RECT)
    except:
        try:
            cv2.grabCut(image, grabMask, boundingRect, None,
                    None, 5, cv2.GC_INIT_WITH_RECT)
        except:
            cv2.grabCut(image, grabMask, (20, 20, rows-40, cols-40), None,
                    None, 5, cv2.GC_INIT_WITH_RECT)
    dstMask = np.where((grabMask == 2) | (
        grabMask == 0), 0, 255).astype('uint8')
    return dstMask


def _clothingEdgeDetect(gray):
    """
    边缘提取

    Args:
        gray 灰度图像
    Return:
        edges 边缘图像
    """
    # Canny边缘检测
    edges = cv2.Canny(gray, 100, 200, apertureSize=5)
    # 形态学闭操作修复断线
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    return edges


def _pantsEdgeDetect(gray):
    """
    边缘提取

    Args:
        gray 灰度图像
    Return:
        edges 边缘图像
    """
    # Canny边缘检测
    edges = cv2.Canny(gray, 100, 200, apertureSize=3)
    # 形态学闭操作修复断线
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    return edges


def _preProcess(image):
    """
    图像预处理

    Args:
        image 原图像
    Return:
        gray 预处理后的灰度图
    """
    # 高斯模糊进行降噪
    image = cv2.GaussianBlur(image, (3, 3), 0)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray


def cut(image, isClothing):
    """
    分割

    Args:
        image 原图像
    Return:
        dst 分割后的图像
        mask 掩膜
    """
    # Step 1: 图像预处理
    grayImage = _preProcess(image.copy())

    if isClothing:
        # Step 2: 边缘提取
        edges = _clothingEdgeDetect(grayImage.copy())
        # Step 3: 分割，并获得分割掩模
        mask = _cutClothing(image.copy(), grayImage.copy(), edges.copy())
        # Step 4: 优化上衣掩膜
        mask = _optimizeClothingMask(mask.copy())
    else:
        # Step 2: 边缘提取
        edges = _pantsEdgeDetect(grayImage.copy())
        # Step 3: 分割，并获得分割掩模
        mask = _cutPants(image.copy(), grayImage.copy(), edges.copy())
        # Step 4: 优化下装掩膜
        mask = _optimizePantsMask(mask.copy())

    # Step 5: 生成最终图像
    dst = image * (mask[:, :, np.newaxis] / 255)
    return mask, dst
