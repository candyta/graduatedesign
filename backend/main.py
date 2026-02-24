# -*- coding: utf-8 -*-
import toml
import argparse
import os
import SimpleITK as sitk
from ct2mcnp.generator import CTVoxel, MCNPGenerator

# 分割 CT 图像的函数
def split_ct_image_slices(ct_image, axis='Z'):
    """
    将 CT 图像按指定的轴（X、Y 或 Z）分割成切片。
    
    :param ct_image: 输入的 CT 图像
    :param axis: 分割的方向（'X'、'Y'、'Z'）
    :return: 切片图像列表
    """
    size = ct_image.GetSize()
    slices = []

    if axis == 'X':
        # 按 X 轴分割，获取每个切片
        for i in range(size[0]):
            region = sitk.RegionOfInterest(ct_image, (1, size[1], size[2]), (i, 0, 0))
            slices.append(region)
    elif axis == 'Y':
        # 按 Y 轴分割，获取每个切片
        for i in range(size[1]):
            region = sitk.RegionOfInterest(ct_image, (size[0], 1, size[2]), (0, i, 0))
            slices.append(region)
    elif axis == 'Z':
        # 按 Z 轴分割，获取每个切片
        for i in range(size[2]):
            region = sitk.RegionOfInterest(ct_image, (size[0], size[1], 1), (0, 0, i))
            slices.append(region)
    
    return slices

# CT 文件处理函数
def generate_process(ct_path, config, base_out_path, split_axis='Z'):
    """
    生成 MCNP 输入文件，支持按切片分割
    :param ct_path: CT 图像路径
    :param config: 配置文件
    :param base_out_path: 输出的基本目录
    :param split_axis: 分割轴（X、Y 或 Z）
    """
    print(f"Processing CT file: {ct_path}")
    try:
        ct_image = sitk.ReadImage(ct_path)  # 使用 SimpleITK 读取 CT 图像
        print(f"Successfully read CT image: {ct_path}")
    except Exception as e:
        print(f"Error reading CT image {ct_path}: {e}")
        return

    # 直接在 C:/i 中生成文件，不创建子文件夹
    out_path = base_out_path  # 输出目录改为 C:/i，去掉子文件夹创建部分
    print(f"Output directory: {out_path}")

    # 分割 CT 图像
    slices = split_ct_image_slices(ct_image, axis=split_axis)

    # 为每个切片生成一个 MCNP 输入文件
    for i, slice_ct in enumerate(slices):
        # 生成文件路径，将切片保存到 C:/i 文件夹内，文件名为 1.inp, 2.inp, ...
        mcnp_input_path = os.path.join(out_path, f"{i+1}.inp")
        print(f"Creating MCNP input file for slice {i+1}...", end="\t")

        # 创建 MCNP 输入文件生成器对象并生成文件
        try:
            generator = MCNPGenerator(slice_ct, config, mcnp_input_path)
            generator.run()  # 调用生成函数生成 MCNP 输入文件
            print(f"Generation complete for slice {i+1}")
        except Exception as e:
            print(f"Error generating MCNP input file for slice {i+1}: {e}")
    
    # 返回生成的文件夹路径，用于 index.js 检查
    return out_path

if __name__ == '__main__':
    # 设置命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str, default="./config.toml", 
                        help="Path to MCNP generator config file ended with 'toml'. Default: './config.toml'")
    parser.add_argument("-d", "--dirpath", type=str, default="./inp", help="Path to the directory that contains output files. Default: './inp'")
    parser.add_argument("--ct", type=str, required=True, help="Path to the CT file or directory of CT files")
    parser.add_argument("--axis", type=str, choices=['X', 'Y', 'Z'], default='Z', help="Direction to split CT images. Options: X, Y, Z. Default: Z")
    args = parser.parse_args()

    # 获取传入的参数
    config_path = args.config
    ct_path = args.ct
    output_path = args.dirpath
    split_axis = args.axis  # 读取分割方向

    # 输出路径和配置文件路径
    print(f"Configuration path: {config_path}")
    print(f"CT path: {ct_path}")
    print(f"Output path: {output_path}")

    # 加载配置文件
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = toml.load(f)
            print("Successfully loaded MCNP generator config!")
    except Exception as e:
        print(f"Error loading configuration file: {e}")
        exit(1)

    # 确保输出路径存在
    if not os.path.exists(output_path):
        print(f"Creating output directory: {output_path}")
        os.makedirs(output_path)

    # 处理 CT 文件路径
    if os.path.isdir(ct_path):  # 如果是目录
        print(f"CT path is a directory, processing all files inside {ct_path}")
        for ct_file in os.listdir(ct_path):
            if ct_file.lower().endswith(('.nii', '.nii.gz', '.dcm')):  # 只处理有效的CT文件
                one_ct_path = os.path.join(ct_path, ct_file)
                print(f"Processing CT file: {one_ct_path}")
                output_folder = generate_process(one_ct_path, config, output_path, split_axis)  # 按指定方向分割
                print(f"Generated output in: {output_folder}")
            else:
                print(f"Skipping non-CT file: {ct_file}")
    else:  # 如果是单个文件
        print(f"CT path is a single file: {ct_path}")
        output_folder = generate_process(ct_path, config, output_path, split_axis)  # 按指定方向分割
        print(f"Generated output in: {output_folder}")

    print("Processing complete.")
