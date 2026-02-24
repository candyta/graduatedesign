const path = require('path');
const fs = require('fs-extra');
const { exec } = require('child_process');
const util = require('util');
const execAsync = util.promisify(exec);
const Jimp = require('jimp');
const colormap = require('colormap');

/**
 * 生成剂量图像切片，并应用热力图颜色
 * @param {string} npyPath 剂量图路径（.npy）
 * @param {string} outputDir 输出切片路径
 * @param {string} refNiiPath 参考NIfTI图像（.nii）
 * @returns {Promise<{axial: string[], coronal: string[], sagittal: string[]}>}
 */
async function processDoseDataFile(npyPath, outputDir, refNiiPath) {
    const doseNiiPath = npyPath.replace(/\.npy$/, '.nii');
    const resampleScript = path.join(__dirname, 'resample_npy_to_nii.py');
    const previewScript = path.join(__dirname, 'nii_preview.py');

    console.log('[DEBUG] 开始执行 processDoseDataFile');
    console.log('[DEBUG] npyPath:', npyPath);
    console.log('[DEBUG] doseNiiPath:', doseNiiPath);
    console.log('[DEBUG] refNiiPath:', refNiiPath);

    try {
        // 执行 NPY 转 NII 的脚本
        await execAsync(`python "${resampleScript}" "${npyPath}" "${refNiiPath}" "${doseNiiPath}"`);
        console.log('[DEBUG] resample 脚本执行成功');

        // 执行生成图像的脚本，并将其生成的图像应用热力图
        await execAsync(`python "${previewScript}" "${doseNiiPath}" "${outputDir}"`);
        console.log('[DEBUG] 预览脚本执行成功');
    } catch (e) {
        console.error('[ERROR] Python 脚本执行失败:', e.message);
        throw e;
    }

    // 读取生成的图像文件，并应用热力图颜色映射
    const result = {};
    const views = ['axial', 'coronal', 'sagittal'];
    for (const view of views) {
        const viewFolder = path.join(outputDir, view);
        const files = await fs.readdir(viewFolder);

        result[view] = [];
        for (const file of files) {
            const filePath = path.join(viewFolder, file);
            const image = await Jimp.read(filePath);

            // 将图像数据转化为热力图并直接替代原图像
            const heatmapImage = await generateHeatmapImage(image);

            // 用热力图直接覆盖原图像
            await heatmapImage.writeAsync(filePath); // 覆盖原图像

            result[view].push(filePath);  // 保存覆盖后的文件路径
        }
    }

    return result;
}

/**
 * 将图像数据应用热力图颜色映射
 * @param {Jimp} image 图像对象
 * @returns {Promise<Jimp>} 带热力图颜色的图像
 */
async function generateHeatmapImage(image) {
    const width = image.bitmap.width;
    const height = image.bitmap.height;

    // 获取图像的像素数据
    const pixels = [];
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const color = image.getPixelColor(x, y);
            const rgba = Jimp.intToRGBA(color);
            pixels.push(rgba);
        }
    }

    // 获取热力图颜色映射
    const colormapOptions = {
        colormap: 'hot',
        nshades: 256,
        format: 'rgba',
        alpha: 1
    };
    const colorMap = colormap(colormapOptions);

    // 为每个像素应用热力图颜色
    for (let i = 0; i < pixels.length; i++) {
        const pixel = pixels[i];
        const value = pixel.r / 255;

        // 获取热力图颜色
        const color = colorMap[Math.floor(value * (colorMap.length - 1))];
        const rgba = [color[0], color[1], color[2], 255];

        // 更新像素颜色
        const x = i % width;
        const y = Math.floor(i / width);
        image.setPixelColor(Jimp.rgbaToInt(rgba[0], rgba[1], rgba[2], rgba[3]), x, y);
    }

    return image;
}

module.exports = { processDoseDataFile };
