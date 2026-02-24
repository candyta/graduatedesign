import numpy as np
import matplotlib.pyplot as plt
import re
import os
import sys

def parse_meshal_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # 提取 X 和 Y 网格边界
    x_match = re.search(r'X direction:\s+([\s\S]+?)Y direction:', content)
    y_match = re.search(r'Y direction:\s+([\s\S]+?)Z direction:', content)

    if not x_match or not y_match:
        raise ValueError("找不到 X 或 Y 网格方向")

    x_bins = np.array([float(x) for x in x_match.group(1).split()])
    y_bins = np.array([float(y) for y in y_match.group(1).split()])

    x_size = len(x_bins) - 1
    y_size = len(y_bins) - 1

    # 初始化剂量矩阵
    dose_matrix = np.zeros((x_size, y_size))

    # 提取数据行（格式为 X Y Z Result RelError）
    data_lines = re.findall(
        r'^\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+Ee\d\.]+)\s+([-+Ee\d\.]+)',
        content, re.MULTILINE
    )

    for x_val, y_val, _, dose_val, _ in data_lines:
        x = float(x_val)
        y = float(y_val)
        dose = float(dose_val)

        # 定位坐标对应的网格
        i = np.searchsorted(x_bins, x, side='right') - 1
        j = np.searchsorted(y_bins, y, side='right') - 1

        if 0 <= i < x_size and 0 <= j < y_size:
            dose_matrix[i, j] = dose

    return dose_matrix.T, x_size, y_size  # 注意转置以便与图像坐标匹配


def plot_dose_image(dose_matrix, output_path):
    plt.figure(figsize=(dose_matrix.shape[1] / 100, dose_matrix.shape[0] / 100), dpi=100)

    # 取剂量的对数值（避免0值的情况）
    dose_matrix_log = np.log10(dose_matrix + 1e-6)

    plt.imshow(dose_matrix_log, cmap='inferno', origin='lower', aspect='auto')
    plt.axis('off')  # 不显示坐标轴
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)  # 去除边距
    # 删除颜色条
    # plt.colorbar()  # 注释掉这行来去掉颜色条
    plt.savefig(output_path, dpi=300, bbox_inches='tight', pad_inches=0)
    plt.close()
    print(f"图像已保存为: {output_path}")


def convert_o_to_png(input_dir, output_dir):
    # 获取输入目录中的所有文件，并按自然数顺序排序
    filenames = sorted(
        (filename for filename in os.listdir(input_dir) if filename.endswith('_o')),
        key=lambda x: int(re.search(r'(\d+)_o', x).group(1))  # 按文件名中的数字进行排序
    )

    # 遍历文件
    for filename in filenames:
        file_path = os.path.join(input_dir, filename)

        try:
            print(f"开始处理文件: {filename}")
            base_name = os.path.splitext(filename)[0]
            output_path = os.path.join(output_dir, base_name + ".png")
            
            # 解析文件并生成剂量矩阵
            dose_matrix, _, _ = parse_meshal_file(file_path)
            
            # 生成并保存图像
            plot_dose_image(dose_matrix, output_path)
        except Exception as e:
            print(f"处理文件 {filename} 时发生错误: {e}")


def main():
    # 获取输入目录和输出目录
    if len(sys.argv) != 3:
        print("用法: python o2png.py <输入文件夹路径> <输出文件夹路径>")
        return

    input_dir = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.isdir(input_dir):
        print(f"目录不存在: {input_dir}")
        return

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    convert_o_to_png(input_dir, output_dir)


if __name__ == "__main__":
    main()
