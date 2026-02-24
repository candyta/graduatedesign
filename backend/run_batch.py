import os
import subprocess
import shutil
import time
import sys

# 设置路径
g5_bat_path = r"D:\LANL\g5.bat"
input_dir = r"C:\i"
output_dir = r"C:\o"
backend_dir = r"C:\my-app3\web\backend"  # backend目录
dose_results_dir = r"C:\my-app3\web\backend\dose_results"  # 剂量结果目录

# 确保输出目录和剂量结果目录存在
os.makedirs(output_dir, exist_ok=True)
os.makedirs(dose_results_dir, exist_ok=True)

# 获取传入的文件列表
input_files = sys.argv[1:]

if not input_files:
    print("没有传入文件路径，请提供输入文件。")
    sys.exit(1)

print(f"Python接收到的参数数量: {len(input_files)}")
for i, f in enumerate(input_files):
    print(f"  参数 {i + 1}: {f}")

# 常见输出文件扩展名
output_extensions = [".o", ".r", ".s", ".p", ".w"]

WAIT_TIMEOUT = 1200  # 等待时间为 20 分钟
WAIT_INTERVAL = 20   # 每次检查文件的间隔时间为 20 秒

# 函数：获取下一个可用的文件名
def get_next_filename():
    counter = 1
    # 检查输出目录中是否已存在相同名称的文件
    while os.path.exists(os.path.join(output_dir, f"{counter}_o")):
        counter += 1
    return f"{counter}_o"

for file_path in input_files:
    base_name = os.path.basename(file_path)
    base_name_without_ext = os.path.splitext(base_name)[0]  # 去掉扩展名
    inp_target_path = os.path.join(input_dir, base_name)
    bare_target_path = os.path.join(input_dir, base_name_without_ext)

    print(f"\n==== 正在处理: {file_path} ====")

    # 如果输入文件不在 input_dir 中，复制进去
    if os.path.abspath(file_path) != os.path.abspath(inp_target_path):
        shutil.copy(file_path, inp_target_path)
        print(f"已将输入文件复制到处理目录: {inp_target_path}")

    # 再复制一个无扩展名版本
    shutil.copy(inp_target_path, bare_target_path)
    print(f"已创建无扩展名副本用于 MCNP 运行: {bare_target_path}")

    print(f"将执行的 g5.bat 命令: \"{g5_bat_path}\" \"{base_name_without_ext}\"")

    try:
        result = subprocess.run(
            [g5_bat_path, base_name_without_ext],   
            cwd=input_dir,
            shell=True,
            capture_output=True,
            text=True
        )

        print("g5.bat 执行返回码:", result.returncode)
        if result.stdout:
            print("g5.bat 标准输出:\n", result.stdout)
        if result.stderr:
            print("g5.bat 错误输出:\n", result.stderr)

        if result.returncode != 0:
            print(f"调用 g5.bat 失败，跳过: {base_name}")
            continue

    except Exception as e:
        print(f"执行 g5.bat 时出错: {e}")
        continue

    # 等待输出文件出现
    print("等待 MCNP 输出文件生成中...")
    success = False
    start_time = time.time()

    while time.time() - start_time < WAIT_TIMEOUT:
        for ext in output_extensions:
            result_file = os.path.join(input_dir, base_name_without_ext + ext)
            print(f"检查文件: {result_file}")
            if os.path.exists(result_file):
                print(f"发现输出文件: {result_file}")
                success = True
                break
        if success:
            break
        time.sleep(WAIT_INTERVAL)

    if not success:
        print(f"未在规定时间内生成输出文件，跳过: {base_name}")
        continue

    # 打印生成文件的详细信息
    print("已生成的文件列表：")
    for ext in output_extensions:
        result_file = os.path.join(input_dir, base_name_without_ext + ext)
        if os.path.exists(result_file):
            print(f"  {result_file} （创建时间：{time.ctime(os.path.getctime(result_file))}）")

    # 首先检查是否生成了mesh文件
    mesh_files = [f for f in os.listdir(input_dir) if f.startswith("mesh")]
    
    if not mesh_files:
        print(f"未找到任何需要移动的输出文件（以 mesh 开头的文件），跳过: {base_name}")
    else:
        print(f"\n找到 {len(mesh_files)} 个mesh文件: {mesh_files}")
        
        # ========== 步骤1：转换meshtal为npy（在移动前） ==========
        print("\n[步骤1: 转换meshtal为npy格式]")
        
        extract_script = os.path.join(backend_dir, "extract_dose_from_mcnp.py")
        npy_output = os.path.join(dose_results_dir, f"dose_{base_name_without_ext}.npy")
        
        try:
            # 传入.o文件路径，脚本会在同目录下找meshtal
            output_o_file = os.path.join(input_dir, base_name_without_ext + ".o")
            
            if os.path.exists(output_o_file):
                print(f"调用剂量提取脚本: {extract_script}")
                print(f".o文件: {output_o_file}")
                print(f"目标npy: {npy_output}")
                
                # 构造命令
                python_exe = sys.executable
                extract_cmd = [python_exe, extract_script, output_o_file, npy_output]
                
                print(f"执行命令: {' '.join(extract_cmd)}")
                
                # 【修复】使用二进制模式读取输出，避免编码问题
                result = subprocess.run(
                    extract_cmd,
                    capture_output=True,
                    text=False  # 使用二进制模式
                )
                
                if result.returncode == 0:
                    print(f"[成功] 剂量数据已转换为npy: {npy_output}")
                    
                    # 验证npy文件是否成功生成
                    if os.path.exists(npy_output):
                        file_size = os.path.getsize(npy_output)
                        print(f"NPY文件大小: {file_size} bytes")
                    else:
                        print("[警告] NPY文件未生成")
                    
                    # 安全打印输出（跳过可能包含Unicode的内容）
                    if result.stdout:
                        try:
                            stdout_text = result.stdout.decode('utf-8', errors='ignore')
                            # 只打印ASCII部分，移除特殊字符
                            ascii_text = stdout_text.encode('ascii', errors='ignore').decode('ascii')
                            if ascii_text.strip():
                                print("提取脚本输出:")
                                print(ascii_text)
                        except:
                            print("提取脚本有输出（含特殊字符，已省略）")
                else:
                    print(f"[警告] 剂量提取失败 (返回码: {result.returncode})")
                    if result.stderr:
                        try:
                            stderr_text = result.stderr.decode('utf-8', errors='ignore')
                            ascii_text = stderr_text.encode('ascii', errors='ignore').decode('ascii')
                            if ascii_text.strip():
                                print("错误输出:")
                                print(ascii_text)
                        except:
                            print("有错误输出（含特殊字符）")
                
            else:
                print(f"[警告] 未找到输出文件: {output_o_file}")
                print("无法执行剂量提取")
                    
        except Exception as e:
            print(f"[警告] 转换npy时出错: {e}")
            import traceback
            traceback.print_exc()
        
        # ========== 步骤2：移动mesh文件到输出目录 ==========
        print("\n[步骤2: 移动mesh文件]")
        for file in mesh_files:
            result_file = os.path.join(input_dir, file)
            if os.path.exists(result_file):
                # 获取下一个可用的文件名
                new_filename = get_next_filename()
                dest_file = os.path.join(output_dir, f"{new_filename}")
                print(f"准备移动文件: {result_file} 到 {dest_file}")
                shutil.move(result_file, dest_file)
                print(f"成功移动: {os.path.basename(result_file)} 到 {dest_file}")

print("全部输入文件处理完毕！")