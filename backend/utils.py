import os
import matplotlib.pyplot as plt

def save_slices(data, out_dir, view, alpha=0.5, base=None):
    """
    保存切片图像，支持与底图叠加。
    
    :param data: 剂量图数据 (已归一化)
    :param out_dir: 输出根目录
    :param view: axial / coronal / sagittal
    :param alpha: 剂量透明度
    :param base: 可选的底图（已归一化 numpy 数组）
    """
    view_dir = os.path.join(out_dir, view)
    os.makedirs(view_dir, exist_ok=True)

    num_slices = data.shape[0]
    for i in range(num_slices):
        fig, ax = plt.subplots()
        ax.axis('off')

        if base is not None:
            base_slice = base[i, :, :]
            ax.imshow(base_slice, cmap='gray')

        dose_slice = data[i, :, :]
        ax.imshow(dose_slice, cmap='hot', alpha=alpha)

        save_path = os.path.join(view_dir, f'{view}_{i}.png')
        plt.savefig(save_path, bbox_inches='tight', pad_inches=0)
        plt.close()
