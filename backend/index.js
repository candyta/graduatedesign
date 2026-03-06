const express = require('express');
const multer = require('multer');
const fs = require('fs-extra');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const cors = require('cors');
const compressing = require('compressing');
const execAsync = util.promisify(exec);
const app = express();
const { processDoseDataFile } = require('./mcnp2png');
const zlib = require('zlib');

const PYTHON_PATH = 'D:\\python.exe';
console.log(`[初始化] 使用Python: ${PYTHON_PATH}`);

// 中间件配置
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(cors({
    origin: ['http://localhost:8080'], // 前端地址
    credentials: true,
    methods: ['GET', 'POST', 'OPTIONS']
}));
// 提供静态文件服务
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// 目录配置
const DIRS = {
    UPLOADS: path.join(__dirname, 'uploads'),
    INPUT: 'C:/i',
    OUTPUT: 'C:/o',
    DOSE_PNG: 'C:/my-app3/web/backend/dosepng',
    LOGS: 'logs',
};
app.use('/dosepng', express.static(DIRS.DOSE_PNG));
app.use('/plus', express.static(path.join(__dirname, 'plus')));
app.use('/dvh', express.static(path.join(__dirname, 'dvh')));
// ==================== 初始化系统 ====================
function initializeSystem() {
    Object.values(DIRS).forEach(dir => {
        fs.ensureDirSync(dir);
        console.log(`[初始化] 目录已创建: ${dir}`);
    });

    const logStream = fs.createWriteStream(path.join(DIRS.LOGS, 'backend.log'), { flags: 'a' });
    console.log(`[初始化] 日志将记录到: ${path.join(DIRS.LOGS, 'backend.log')}`);

    return logStream;
}

const logStream = initializeSystem();

// ==================== 文件上传配置 ====================
const niiStorage = multer.diskStorage({
    destination: (req, file, cb) => {
        const folderName = `nii_${Date.now()}`;
        const uploadPath = path.join(DIRS.UPLOADS, folderName);
        fs.ensureDirSync(uploadPath);
        req.uploadFolder = folderName;
        cb(null, uploadPath);
    },
    filename: (req, file, cb) => {
        cb(null, file.originalname);
    }
});

const uploadNii = multer({
    storage: niiStorage,
    fileFilter: (req, file, cb) => {
        if (file.originalname.endsWith('.nii.gz')) {
            cb(null, true);
        } else {
            cb(new Error('仅支持.nii.gz文件'));
        }
    },
    limits: { fileSize: 1000 * 1024 * 1024 }
});

const upload = multer({
    dest: 'uploads/',  // 设置上传文件的存储目录
    limits: {
        fileSize: 1000 * 1024 * 1024, // 最大文件大小为10MB，根据需要调整
    },
    fileFilter: (req, file, cb) => {
        // 只接受 .npy 文件
        if (!file.originalname.match(/\.(npy)$/)) {
            return cb(new Error('只能上传 .npy 文件'), false);
        }
        cb(null, true);
    }
});
// ==================== NPY 文件上传配置 ====================
const npyStorage = multer.diskStorage({
    destination: (req, file, cb) => {
        // 设置上传路径为 `dosepng` 文件夹
        const dosePngDir = DIRS.DOSE_PNG;
        fs.ensureDirSync(dosePngDir); // 确保文件夹存在
        cb(null, dosePngDir); // 上传到 `dosepng` 文件夹
    },
    filename: (req, file, cb) => {
        // 保持原始文件名
        cb(null, file.originalname);
    }
});

// 使用 multer 配置上传 .npy 文件
const uploadNpy = multer({
    storage: npyStorage,
    fileFilter: (req, file, cb) => {
        // 只接受 .npy 文件
        if (!file.originalname.match(/\.(npy)$/)) {
            return cb(new Error('只能上传 .npy 文件'), false);
        }
        cb(null, true);
    },
    limits: { fileSize: 1000 * 1024 * 1024 } // 限制文件最大为 10MB
});

const uploadOrganMasks = multer({
    storage: multer.diskStorage({
        destination: (req, file, cb) => {
            const organDir = path.join(__dirname, 'organ');  // 设定目标目录为 `organ` 目录
            fs.ensureDirSync(organDir);  // 确保目录存在
            cb(null, organDir);  // 将文件保存到指定目录
        },
        filename: (req, file, cb) => {
            cb(null, file.originalname);  // 保持原始文件名
        }
    }),
    fileFilter: (req, file, cb) => {
        // 只允许上传 .nii.gz 文件
        if (file.originalname.endsWith('.nii.gz')) {
            cb(null, true);
        } else {
            cb(new Error('仅支持 .nii.gz 文件'), false);
        }
    },
    limits: { fileSize: 1000 * 1024 * 1024 }  // 限制文件大小为 1MB
});

// ==================== 日志函数 ====================
function log(message, level = 'info') {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}][${level.toUpperCase()}] ${message} \n`;
    logStream.write(logMessage);
    console[level](logMessage.trim());
}

// ==================== API端点 ====================

app.post('/upload-nii', uploadNii.single('niiFile'), async (req, res) => {
    try {
        const uploadedFolder = path.join(DIRS.UPLOADS, req.uploadFolder);
        const originalFilename = req.file.originalname;

        // 原始上传的 .gz 文件路径
        const gzPath = path.join(uploadedFolder, originalFilename);
        console.log(`Received file: ${originalFilename}`);
        console.log(`Attempting to decompress: ${gzPath}`);

        // 解压后的 .nii 文件路径
        const niiPath = path.join(uploadedFolder, originalFilename.replace(/\.gz$/, ''));

        // 解压 .nii.gz → .nii
        await compressing.gzip.uncompress(gzPath, niiPath);
        console.log(`Decompressed to: ${niiPath}`);

        const niiExists = await fs.pathExists(niiPath);
        if (!niiExists) {
            throw new Error('.nii 文件未成功解压');
        }
        console.log('Successfully decompressed .nii.gz to .nii');

        const npyPath = niiPath.replace('.nii', '.npy');
        const niiToNpyScript = path.join(__dirname, 'nii_to_npy.py');

        // 执行转换命令
        const { stdout: npyStdout, stderr: npyStderr } = await execAsync(
            `"${PYTHON_PATH}" "${niiToNpyScript}" "${niiPath}" "${npyPath}"`
        );
        console.log('Numpy conversion stdout:', npyStdout);
        console.log('Numpy conversion stderr:', npyStderr);

        if (!(await fs.pathExists(npyPath))) {
            throw new Error('.npy 文件未成功生成');
        }
        console.log('Successfully converted .nii to .npy');

        // =========== 3. 调用 Python 生成切片 =========== 
        const outputDir = path.join(uploadedFolder, 'slices');
        await execAsync(`python nii_preview.py "${niiPath}" "${outputDir}"`);
        console.log(`Generated slices and saved in: ${outputDir}`);

        // 构建切片结果结构
        const result = {
            axial: [],
            coronal: [],
            sagittal: [],
            maxSlices: {
                axial: 0,
                coronal: 0,
                sagittal: 0
            }
        };

        const views = ['axial', 'coronal', 'sagittal'];
        for (const view of views) {
            const viewDir = path.join(outputDir, view);
            const files = await fs.readdir(viewDir);
            console.log(`Found ${files.length} ${view} slices`);
            result[view] = files.sort().map(file =>
                `/uploads/${req.uploadFolder}/slices/${view}/${file}` // 确保路径正确
            );
            result.maxSlices[view] = files.length;
        }

        console.log('Returning slice data:', result);

        // 响应前端
        res.json({
            success: true,
            message: '.nii.gz 文件处理成功，MCNP 输入文件、.npy 文件与切片生成完毕',
            folderName: req.uploadFolder,
            niiPath,
            npyPath,
            ...result // 包含生成的切片和最大切片数
        });

    } catch (err) {
        console.error('Error during processing:', err.message);
        res.status(500).json({
            success: false,
            message: '处理失败',
            error: err.message
        });
    }
});



// 构建全身体模的API（改造版: 传递患者参数, 生成多材料lattice几何）
app.post('/build-wholebody-phantom', async (req, res) => {
    try {
        console.log('Received request to build whole-body phantom');

        const niiPath = req.body.niiPath;
        if (!niiPath) {
            throw new Error('NIfTI 文件路径未提供');
        }

        // 从请求中获取患者参数（前端传递）
        const gender = req.body.gender || 'male';
        const tumorRegion = req.body.tumorRegion || '';  // 可选: brain/chest/abdomen等

        console.log(`NIfTI path: ${niiPath}`);
        console.log(`Gender: ${gender}, Tumor region: ${tumorRegion || 'auto-detect'}`);

        // 调用Python脚本构建全身体模
        const phantomScript = path.join(__dirname, 'ct_phantom_fusion.py');
        const outputDir = path.join(__dirname, 'wholebody_phantom');
        fs.ensureDirSync(outputDir);

        // 构建命令: 传递性别和可选的肿瘤区域参数
        let command = `"${PYTHON_PATH}" "${phantomScript}" "${niiPath}" "${outputDir}" --gender "${gender}"`;
        if (tumorRegion) {
            command += ` --region "${tumorRegion}"`;
        }
        console.log(`执行命令: ${command}`);

        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,
            env: {
                ...process.env,
                PYTHONIOENCODING: 'utf-8'
            }
        });

        console.log('Python stdout:', stdout);
        if (stderr) {
            console.error('Python stderr:', stderr);
        }

        // 检查生成的MCNP输入文件
        const mcnpInputFile = path.join(outputDir, 'wholebody_mcnp.inp');
        if (!fs.existsSync(mcnpInputFile)) {
            throw new Error('MCNP输入文件生成失败');
        }

        // 【关键】复制MCNP输入文件到 C:/i/ 目录供MCNP计算使用
        const mcnpInputDir = DIRS.INPUT; // C:/i
        fs.ensureDirSync(mcnpInputDir);
        
        // 【修复】生成最短的文件名：从1开始递增
        // MCNP5要求基础名≤7字符，使用1.inp, 2.inp, 3.inp...
        // 查找现有文件，获取下一个编号
        const existingFiles = fs.readdirSync(mcnpInputDir)
            .filter(f => f.endsWith('.inp') && /^\d+\.inp$/.test(f))
            .map(f => parseInt(f.replace('.inp', '')))
            .filter(n => !isNaN(n));
        
        const nextNumber = existingFiles.length > 0 ? Math.max(...existingFiles) + 1 : 1;
        const targetFileName = `${nextNumber}.inp`;  // 1.inp, 2.inp, 3.inp...
        const targetFilePath = path.join(mcnpInputDir, targetFileName);
        
        // 复制文件
        fs.copyFileSync(mcnpInputFile, targetFilePath);
        console.log(`MCNP输入文件已复制到: ${targetFilePath}`);
        console.log(`文件基础名: ${nextNumber} (${nextNumber.toString().length}字符)`);

        console.log('全身体模构建成功');

        // 从fusion_metadata.json读取自动识别的解剖区域
        let anatomicalRegion = '';
        const metadataPath = path.join(outputDir, 'fusion_metadata.json');
        if (fs.existsSync(metadataPath)) {
            const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'));
            anatomicalRegion = (metadata.registration && metadata.registration.anatomical_region) || '';
        }
        console.log(`检测到的解剖区域: ${anatomicalRegion}`);

        res.json({
            success: true,
            message: '全身体模构建完成',
            phantomDir: outputDir,
            mcnpInputFile: mcnpInputFile,
            mcnpInputFileInI: targetFilePath,
            mcnpFileName: targetFileName,
            anatomicalRegion: anatomicalRegion
        });

    } catch (err) {
        console.error('全身体模构建失败:', err.message);
        res.status(500).json({
            success: false,
            message: '全身体模构建失败',
            error: err.message
        });
    }
});

// 生成全身剂量分布图的API
app.post('/generate-wholebody-dose-map', async (req, res) => {
    try {
        console.log('Received request to generate whole-body dose map');

        const { axialImagePath } = req.body;

        // 剂量数据目录 - 检查多个可能的位置
        const dosePngDir = DIRS.DOSE_PNG;
        const doseResultsDir = path.join(__dirname, 'dose_results');
        
        // ===== 步骤1: 查找剂量文件（.npy） =====
        let doseNpyPath = null;
        let doseFiles = [];
        
        // 优先在dose_results中查找（run_batch.py生成的位置）
        if (fs.existsSync(doseResultsDir)) {
            doseFiles = fs.readdirSync(doseResultsDir).filter(f => f.endsWith('.npy'));
            if (doseFiles.length > 0) {
                // 使用最新的文件（按修改时间排序）
                const sortedFiles = doseFiles.map(f => ({
                    name: f,
                    time: fs.statSync(path.join(doseResultsDir, f)).mtime.getTime()
                })).sort((a, b) => b.time - a.time);
                
                doseNpyPath = path.join(doseResultsDir, sortedFiles[0].name);
                console.log(`✓ 在dose_results中找到剂量文件: ${doseNpyPath}`);
            }
        }
        
        // 如果dose_results中没有，再在dose_png目录查找
        if (!doseNpyPath) {
            if (fs.existsSync(dosePngDir)) {
                doseFiles = fs.readdirSync(dosePngDir).filter(f => f.endsWith('.npy'));
                if (doseFiles.length > 0) {
                    doseNpyPath = path.join(dosePngDir, doseFiles[0]);
                    console.log(`✓ 在dose_png中找到剂量文件: ${doseNpyPath}`);
                }
            }
        }
        
        if (!doseNpyPath) {
            throw new Error('未找到剂量数据文件(.npy)，请确保MCNP计算已完成且dose提取成功');
        }
        
        console.log(`使用剂量文件: ${doseNpyPath}`);
        
        // ===== 步骤2: 查找参考NIfTI文件 =====
        // 优先使用融合后的全身体模（fused_phantom.nii.gz），
        // 它包含完整的254×127×222体素全身结构，
        // 而原始CT只是局部扫描，用它做背景会把剂量图裁剪到局部范围
        let refNiiPath = null;

        // 方法1（最优先）：使用 wholebody_phantom/fused_phantom.nii.gz
        const fusedPhantomPath = path.join(__dirname, 'wholebody_phantom', 'fused_phantom.nii.gz');
        if (fs.existsSync(fusedPhantomPath)) {
            refNiiPath = fusedPhantomPath;
            console.log(`✓ 使用全身融合体模作为参考: ${refNiiPath}`);
        }

        // 方法2: 从session_info读取（fallback，仅当没有fused_phantom时）
        if (!refNiiPath) {
            const sessionInfoPath = path.join(DIRS.OUTPUT, 'session_info.json');
            if (fs.existsSync(sessionInfoPath)) {
                try {
                    const sessionInfo = fs.readJsonSync(sessionInfoPath);
                    if (sessionInfo.ct_nii_path && fs.existsSync(sessionInfo.ct_nii_path)) {
                        refNiiPath = sessionInfo.ct_nii_path;
                        console.log(`[警告] 未找到全身体模，回退到局部CT: ${refNiiPath}`);
                    }
                } catch (err) {
                    console.log('读取session_info失败:', err.message);
                }
            }
        }

        // 方法3: 从axialImagePath提取（fallback）
        if (!refNiiPath && axialImagePath) {
            try {
                const pathParts = axialImagePath.split('/');
                const uploadFolder = pathParts[2];
                const uploadPath = path.join(DIRS.UPLOADS, uploadFolder);
                if (fs.existsSync(uploadPath)) {
                    const uploadedFiles = fs.readdirSync(uploadPath);
                    const niiFile = uploadedFiles.find(f => f.endsWith('.nii'));
                    if (niiFile) {
                        refNiiPath = path.join(uploadPath, niiFile);
                        console.log(`[警告] 回退到上传CT: ${refNiiPath}`);
                    }
                }
            } catch (err) {
                console.log('从axialImagePath提取CT路径失败:', err.message);
            }
        }

        if (!refNiiPath || !fs.existsSync(refNiiPath)) {
            throw new Error('无法找到参考图像。请先执行"构建全身体模"步骤，确保fused_phantom.nii.gz已生成。');
        }

        console.log(`✓ 验证通过，使用参考NIfTI: ${refNiiPath}`);
        
        // ===== 步骤3: 调用Python脚本生成全身剂量图 =====
        const doseScript = path.join(__dirname, 'dose_to_png.py');
        const outputDir = path.join(dosePngDir, 'wholebody');
        fs.ensureDirSync(outputDir);

        const { hiddenOrgans } = req.body;
        const hiddenOrgansArg = hiddenOrgans && hiddenOrgans.trim()
            ? ` "--hidden-organs=${hiddenOrgans.trim()}"`
            : '';
        const command = `"${PYTHON_PATH}" "${doseScript}" "${doseNpyPath}" "${outputDir}" "${refNiiPath}"${hiddenOrgansArg}`;
        console.log(`执行命令: ${command}`);

        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,
            env: {
                ...process.env,
                PYTHONIOENCODING: 'utf-8'
            }
        });

        console.log('Python stdout:', stdout);
        if (stderr) {
            console.error('Python stderr:', stderr);
        }

        // ===== 步骤4: 读取生成的剂量切片 =====
        const result = {
            doseAxial: [],
            doseCoronal: [],
            doseSagittal: []
        };

        const views = ['axial', 'coronal', 'sagittal'];
        for (const view of views) {
            const viewDir = path.join(outputDir, view);
            if (fs.existsSync(viewDir)) {
                const files = await fs.readdir(viewDir);
                if (files.length > 0) {
                    result[`dose${view.charAt(0).toUpperCase() + view.slice(1)}`] = files
                        .sort()
                        .map(file => `/dosepng/wholebody/${view}/${file}`);
                    console.log(`✓ ${view}视图: ${files.length}张切片`);
                } else {
                    console.log(`⚠ ${view}视图: 未生成切片`);
                }
            } else {
                console.log(`⚠ ${view}视图目录不存在`);
            }
        }

        // 验证至少有一个视图生成了切片
        const totalSlices = result.doseAxial.length + result.doseCoronal.length + result.doseSagittal.length;
        if (totalSlices === 0) {
            throw new Error('未生成任何剂量切片，请检查dose_to_png.py的执行日志');
        }

        console.log(`✓ 全身剂量分布图生成成功，共${totalSlices}张切片`);

        res.json({
            success: true,
            message: '全身剂量分布图生成完成',
            totalSlices,
            ...result
        });

    } catch (err) {
        console.error('❌ 全身剂量分布图生成失败:', err.message);
        res.status(500).json({
            success: false,
            message: '全身剂量分布图生成失败',
            error: err.message,
            troubleshooting: {
                'dose文件': '检查 C:/my-app3/web/backend/dose_results/ 目录',
                'CT文件': '检查 C:/my-app3/web/backend/uploads/nii_xxx/ 目录',
                'session': '检查 C:/o/session_info.json 文件',
                'Python脚本': '手动运行 dose_to_png.py 查看详细错误'
            }
        });
    }
});

// ==================== 重新应用器官轮廓过滤 ====================
app.post('/reapply-dose-organs', async (req, res) => {
    try {
        const { hiddenOrgans } = req.body;
        const dosePngDir = DIRS.DOSE_PNG;
        const doseResultsDir = path.join(__dirname, 'dose_results');

        // 查找剂量文件（与 generate-wholebody-dose-map 相同逻辑）
        let doseNpyPath = null;
        if (fs.existsSync(doseResultsDir)) {
            const doseFiles = fs.readdirSync(doseResultsDir).filter(f => f.endsWith('.npy'));
            if (doseFiles.length > 0) {
                const sorted = doseFiles.map(f => ({
                    name: f, time: fs.statSync(path.join(doseResultsDir, f)).mtime.getTime()
                })).sort((a, b) => b.time - a.time);
                doseNpyPath = path.join(doseResultsDir, sorted[0].name);
            }
        }
        if (!doseNpyPath && fs.existsSync(dosePngDir)) {
            const doseFiles = fs.readdirSync(dosePngDir).filter(f => f.endsWith('.npy'));
            if (doseFiles.length > 0) doseNpyPath = path.join(dosePngDir, doseFiles[0]);
        }
        if (!doseNpyPath) throw new Error('未找到剂量数据文件(.npy)');

        // 查找参考NIfTI（优先fused_phantom）
        let refNiiPath = null;
        const fusedPhantomPath = path.join(__dirname, 'wholebody_phantom', 'fused_phantom.nii.gz');
        if (fs.existsSync(fusedPhantomPath)) refNiiPath = fusedPhantomPath;
        if (!refNiiPath) {
            const sessionInfoPath = path.join(DIRS.OUTPUT, 'session_info.json');
            if (fs.existsSync(sessionInfoPath)) {
                try {
                    const info = fs.readJsonSync(sessionInfoPath);
                    if (info.ct_nii_path && fs.existsSync(info.ct_nii_path)) refNiiPath = info.ct_nii_path;
                } catch (_) {}
            }
        }
        if (!refNiiPath) throw new Error('未找到参考NIfTI文件');

        const doseScript = path.join(__dirname, 'dose_to_png.py');
        const outputDir = path.join(dosePngDir, 'wholebody');
        fs.ensureDirSync(outputDir);

        const hiddenOrgansArg = hiddenOrgans && hiddenOrgans.trim()
            ? ` "--hidden-organs=${hiddenOrgans.trim()}"`
            : '';
        const command = `"${PYTHON_PATH}" "${doseScript}" "${doseNpyPath}" "${outputDir}" "${refNiiPath}"${hiddenOrgansArg}`;
        console.log(`[reapply-dose-organs] ${command}`);

        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,
            env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
        });
        console.log('Python stdout:', stdout);
        if (stderr) console.error('Python stderr:', stderr);

        const result = { doseAxial: [], doseCoronal: [], doseSagittal: [] };
        for (const view of ['axial', 'coronal', 'sagittal']) {
            const viewDir = path.join(outputDir, view);
            if (fs.existsSync(viewDir)) {
                const files = await fs.readdir(viewDir);
                result[`dose${view.charAt(0).toUpperCase() + view.slice(1)}`] = files
                    .sort().map(f => `/dosepng/wholebody/${view}/${f}`);
            }
        }

        const totalSlices = result.doseAxial.length + result.doseCoronal.length + result.doseSagittal.length;
        res.json({ success: true, totalSlices, ...result });

    } catch (err) {
        console.error('[reapply-dose-organs] 失败:', err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

// 生成MCNP输入文件的API
app.post('/generate-mcnp-input', async (req, res) => {
    try {
        console.log('Received request to generate MCNP input file');

        // 从请求中获取文件路径
        const niiPath = req.body.niiPath;
        if (!niiPath) {
            throw new Error('NIfTI 文件路径未提供');
        }

        console.log(`Received NIfTI file path: ${niiPath}`);

        // 检查文件路径是否存在
        const niiExists = await fs.pathExists(niiPath);
        if (!niiExists) {
            throw new Error('指定的 NIfTI 文件不存在');
        }

        // 调用 Python 脚本生成 MCNP 输入文件
        const generateMcnpScript = path.join(__dirname, 'main.py');
        console.log(`Running Python script to generate MCNP input file with command: "${PYTHON_PATH}" "${generateMcnpScript}" --ct "${niiPath}" --config "C:/my-app3/web/backend/config.toml" --dirpath "${DIRS.INPUT}"`);

        const command = `"${PYTHON_PATH}" "${generateMcnpScript}" --ct "${niiPath}" --config "C:/my-app3/web/backend/config.toml" --dirpath "${DIRS.INPUT}"`;

        // 执行命令并捕获输出
        const { stdout, stderr } = await execAsync(command);

        // 输出 Python 脚本的输出信息
        console.log('Python script stdout:', stdout);
        console.error('Python script stderr:', stderr);

        // 检查是否有任何以 .inp 结尾的文件
        const inpFiles = await fs.readdir(DIRS.INPUT);
        const inpFileExists = inpFiles.some(file => file.endsWith('.inp'));

        // 如果找到 .inp 文件，则认为生成成功
        if (!inpFileExists) {
            throw new Error('MCNP 输入文件未成功生成');
        }

        console.log('MCNP 输入文件已成功生成:', inpFiles.filter(file => file.endsWith('.inp')));

        // 返回成功的响应
        res.json({
            success: true,
            message: 'MCNP 输入文件生成成功',
            inpFiles: inpFiles.filter(file => file.endsWith('.inp'))  // 返回生成的 .inp 文件名列表
        });

    } catch (err) {
        // 错误处理
        console.error('Error during MCNP input file generation:', err);
        res.status(500).json({
            success: false,
            message: '生成 MCNP 输入文件失败',
            error: err.message
        });
    }
});



app.post('/run-mcnp-computation', async (req, res) => {
    try {
        const inputDir = DIRS.INPUT;
        const outputDir = DIRS.OUTPUT;
        const batchFile = 'ccmd.bat';

        console.log('MCNP computation request received');
        console.log(`Input directory: ${inputDir}`);
        console.log(`Output directory: ${outputDir}`);
        console.log(`Using batch file: ${batchFile}`);

        // 获取所有 MCNP 输入文件
        const mcnpInputFiles = await fs.readdir(inputDir);
        console.log(`Found ${mcnpInputFiles.length} files in the input directory`);

        const inputFiles = mcnpInputFiles.filter(file => file.endsWith('.inp'));
        console.log(`Filtered input files: ${inputFiles}`);

        if (inputFiles.length === 0) {
            console.log('No .inp files found in the input directory');
            return res.status(400).json({
                success: false,
                message: 'No .inp files found in the input directory'
            });
        }

        // 对输入文件按自然数顺序排序
        const sortedInputFiles = inputFiles.sort((a, b) => {
            // 提取文件名中的数字部分并比较
            const numA = parseInt(a.replace(/\D/g, ''));  // 去除非数字字符并转换为数字
            const numB = parseInt(b.replace(/\D/g, ''));
            return numA - numB;  // 按数字顺序排序
        });

        console.log(`Sorted input files: ${sortedInputFiles}`);

        // 执行 MCNP 计算
        const results = [];
        for (const filePath of sortedInputFiles) {
            const fullFilePath = path.join(inputDir, filePath);
            console.log(`Running MCNP calculation for file: ${fullFilePath}`);

            const command = `"${PYTHON_PATH}" "run_batch.py" "${fullFilePath}"`;
            console.log(`Executing command: ${command}`);

            // 使用encoding: 'buffer'避免GBK解码错误，然后手动转换
            const { stdout, stderr } = await execAsync(command, {
                encoding: 'buffer',
                maxBuffer: 10 * 1024 * 1024,
                cwd: __dirname  // ← 添加工作目录，确保run_batch.py在正确的目录运行
            });
            
            // 手动转换为字符串，忽略无法解码的字符
            const stdoutStr = stdout.toString('utf8', 0, stdout.length).replace(/\uFFFD/g, '?');
            const stderrStr = stderr.toString('utf8', 0, stderr.length).replace(/\uFFFD/g, '?');

            // Log the results of the computation
            console.log(`stdout for ${filePath}: ${stdoutStr}`);
            console.log(`stderr for ${filePath}: ${stderrStr}`);

            // 保存计算结果
            results.push({ file: filePath, stdout: stdoutStr, stderr: stderrStr });
        }

        // 将输出文件保存到 OUTPUT 目录
        await fs.ensureDir(outputDir);
        console.log('Ensured output directory exists: ' + outputDir);

        // 【新增】保存session信息供后续dose可视化使用
        try {
            // 查找最新上传的CT文件
            const uploadFolders = await fs.readdir(DIRS.UPLOADS);
            const niiFolders = uploadFolders.filter(f => f.startsWith('nii_'))
                .map(f => ({
                    name: f,
                    path: path.join(DIRS.UPLOADS, f),
                    time: fs.statSync(path.join(DIRS.UPLOADS, f)).mtime.getTime()
                }))
                .sort((a, b) => b.time - a.time);
            
            if (niiFolders.length > 0) {
                const latestFolder = niiFolders[0];
                const files = await fs.readdir(latestFolder.path);
                const niiFile = files.find(f => f.endsWith('.nii'));
                
                if (niiFile) {
                    const ctNiiPath = path.join(latestFolder.path, niiFile);
                    const sessionInfoPath = path.join(outputDir, 'session_info.json');
                    const sessionInfo = {
                        ct_nii_path: ctNiiPath,
                        upload_folder: latestFolder.name,
                        timestamp: new Date().toISOString(),
                        mcnp_files: sortedInputFiles
                    };
                    await fs.writeJson(sessionInfoPath, sessionInfo, { spaces: 2 });
                    console.log('[Session] 已保存session信息:', sessionInfoPath);
                }
            }
        } catch (sessionErr) {
            console.warn('[Session] 保存session信息失败:', sessionErr.message);
        }

        res.json({ success: true, message: 'MCNP计算完毕', results });
        console.log('MCNP computation completed successfully');

    } catch (err) {
        console.error('Error during MCNP computation:', err.message);
        res.status(500).json({
            success: false,
            message: 'MCNP计算失败',
            error: err.message
        });
    }
});



// 4. 生成剂量分布图
app.post('/generate-dose-map', async (req, res) => {
    try {
        const { axialImagePath } = req.body;

        if (!axialImagePath) throw new Error('原图像路径未提供');

        console.log(`接收到的原图像文件夹路径: ${axialImagePath}`);

        const relativeFolderPath = axialImagePath.replace(/^\/uploads\//, '');
        const fullFolderPath = path.join(DIRS.UPLOADS, relativeFolderPath);

        if (!await fs.pathExists(fullFolderPath)) {
            throw new Error(`原图像文件夹不存在: ${fullFolderPath}`);
        }

        const axialFiles = (await fs.readdir(fullFolderPath)).filter(file => file.endsWith('.png'));
        if (axialFiles.length === 0) {
            throw new Error('原图像文件夹中没有找到任何 .png 文件');
        }

        // Step 1: 执行 o2png.py，输入 C:/o，输出到 dosepng 目录
        const o2pngScript = path.join(__dirname, 'o2png.py');
        const doseOutputDir = DIRS.DOSE_PNG;
        await fs.ensureDir(doseOutputDir);

        const doseCmd = `"${PYTHON_PATH}" "${o2pngScript}" "C:/o" "${doseOutputDir}"`;
        const { stdout: doseOut, stderr: doseErr } = await execAsync(doseCmd);
        console.log(`剂量图生成 stdout: ${doseOut}`);
        if (doseErr) console.warn(`剂量图生成 stderr: ${doseErr}`);

        // Step 2: 合成图像输出到 backend/plus/
        const compositeOutputDir = path.join(__dirname, 'plus');
        await fs.ensureDir(compositeOutputDir);

        const doseFiles = (await fs.readdir(doseOutputDir)).filter(f => f.endsWith('.png'));
        if (doseFiles.length === 0) throw new Error('未生成任何剂量图');

        const compositeImagePaths = [];

        for (let i = 0; i < axialFiles.length && i < doseFiles.length; i++) {
            const originalImage = path.join(fullFolderPath, axialFiles[i]);
            const doseImage = path.join(doseOutputDir, doseFiles[i]);
            const outputImage = path.join(compositeOutputDir, axialFiles[i]);

            const originalExists = await fs.pathExists(originalImage);
            const doseExists = await fs.pathExists(doseImage);

            console.log(`准备合成: 原图 ${originalImage} 是否存在: ${originalExists}`);
            console.log(`准备合成: 剂量图 ${doseImage} 是否存在: ${doseExists}`);

            if (!originalExists || !doseExists) {
                console.warn(`跳过第 ${i} 张，因原图或剂量图不存在`);
                continue;
            }

            const dosePlusScript = path.join(__dirname, 'doseplus.py');
            // 使用path.join生成正确格式的路径
            const command = `"${PYTHON_PATH}" "${dosePlusScript}" "${originalImage.replace(/\\/g, '\\\\')}" "${doseImage.replace(/\\/g, '\\\\')}" "${outputImage.replace(/\\/g, '\\\\')}"`;

            console.log(`正在执行合成命令: ${command}`);


            const { stdout, stderr } = await execAsync(command);
            console.log(`合成图像 stdout (${axialFiles[i]}): ${stdout}`);
            if (stderr) console.warn(`合成图像 stderr: ${stderr}`);

            // 检查生成的图像是否存在
            const outputExists = await fs.pathExists(outputImage);
            console.log(`合成图像是否存在: ${outputExists}`);

            if (outputExists) {
                compositeImagePaths.push(`/plus/${axialFiles[i]}`);
            } else {
                console.warn(`合成图像未生成: ${axialFiles[i]}`);
            }
        }

        // 返回合成图像路径
        res.json({
            success: true,
            message: '剂量图已生成并合成成功',
            compositeImagePaths
        });

    } catch (err) {
        console.error('生成剂量分布图失败:', err.message);
        res.status(500).json({
            success: false,
            message: '生成剂量分布图失败',
            error: err.message
        });
    }
});








// ==================== 处理 NPY 文件的 API ====================
app.post('/process-npy', uploadNpy.single('doseFile'), async (req, res) => {
    try {
        // 检查是否上传了文件
        if (!req.file) {
            throw new Error('没有上传 .npy 文件');
        }

        const npyPath = req.file.path;  // 获取上传的 .npy 文件路径
        const baseName = path.basename(npyPath, '.npy');
        const outputDir = path.join(DIRS.DOSE_PNG, baseName);

        console.log('[DEBUG] 收到 .npy 文件路径:', npyPath);

        // ===== 多种方式获取NIfTI路径 =====
        let niiRefPath = null;
        
        // 方法1: 从请求body中获取（如果前端传递了）
        if (req.body.niiPath) {
            niiRefPath = req.body.niiPath.replace(/\.npy$/, '.nii');
            console.log('[DEBUG] 从请求获取NIfTI路径:', niiRefPath);
        }
        
        // 方法2: 从session_info读取
        if (!niiRefPath) {
            const sessionInfoPath = path.join(DIRS.OUTPUT, 'session_info.json');
            if (fs.existsSync(sessionInfoPath)) {
                try {
                    const sessionInfo = fs.readJsonSync(sessionInfoPath);
                    if (sessionInfo.ct_nii_path) {
                        niiRefPath = sessionInfo.ct_nii_path;
                        console.log('[DEBUG] 从session获取NIfTI路径:', niiRefPath);
                    }
                } catch (err) {
                    console.log('[DEBUG] 读取session_info失败:', err.message);
                }
            }
        }
        
        // 方法3: 查找最新上传的.nii文件
        if (!niiRefPath) {
            try {
                const uploadFolders = fs.readdirSync(DIRS.UPLOADS)
                    .filter(f => f.startsWith('nii_'))
                    .map(f => ({
                        name: f,
                        path: path.join(DIRS.UPLOADS, f),
                        time: fs.statSync(path.join(DIRS.UPLOADS, f)).mtime.getTime()
                    }))
                    .sort((a, b) => b.time - a.time);
                
                for (const folder of uploadFolders) {
                    const files = fs.readdirSync(folder.path);
                    const niiFile = files.find(f => f.endsWith('.nii'));
                    if (niiFile) {
                        niiRefPath = path.join(folder.path, niiFile);
                        console.log('[DEBUG] 找到最新NIfTI文件:', niiRefPath);
                        break;
                    }
                }
            } catch (err) {
                console.log('[DEBUG] 查找NIfTI文件失败:', err.message);
            }
        }

        if (!niiRefPath) {
            return res.status(400).json({
                success: false,
                message: '缺少参考 NIfTI 图像路径',
                solution: '请先上传CT图像文件（.nii.gz），或在上传npy时同时提供niiPath参数'
            });
        }

        // 验证路径存在
        if (!fs.existsSync(niiRefPath)) {
            return res.status(400).json({
                success: false,
                message: `NIfTI文件不存在: ${niiRefPath}`,
                solution: '请重新上传CT图像文件'
            });
        }

        console.log('[DEBUG] 参考 NIfTI 文件路径:', niiRefPath);
        console.log('[DEBUG] 输出目录路径:', outputDir);

        // 处理 .npy 文件并生成剂量图像
        const doseImages = await processDoseDataFile(npyPath, outputDir, niiRefPath);

        // 验证生成结果
        const totalImages = doseImages.axial.length + doseImages.coronal.length + doseImages.sagittal.length;
        if (totalImages === 0) {
            throw new Error('未生成任何剂量图像');
        }

        console.log(`✓ NPY文件处理成功，共生成${totalImages}张剂量图像`);

        // 返回生成的图像路径和 NPY 文件路径
        res.json({
            success: true,
            message: `NPY文件上传并生成剂量图像成功（${totalImages}张）`,
            doseNpyPath: npyPath,  // 返回 NPY 文件路径
            totalImages,
            doseImages: {
                axial: doseImages.axial.map(image => `/dosepng/${baseName}/axial/${path.basename(image)}`),
                coronal: doseImages.coronal.map(image => `/dosepng/${baseName}/coronal/${path.basename(image)}`),
                sagittal: doseImages.sagittal.map(image => `/dosepng/${baseName}/sagittal/${path.basename(image)}`),
            }
        });

    } catch (err) {
        console.error('[ERROR] 处理失败:', err.message);
        res.status(500).json({
            success: false,
            message: 'NPY剂量图像生成失败',
            error: err.message,
            troubleshooting: {
                '检查npy文件': '确保上传的是有效的numpy数组文件',
                '检查CT文件': '确保已上传对应的CT图像',
                '查看日志': '检查后端控制台的详细错误信息'
            }
        });
    }
});


// ==================== 生成 DVH 图像的 API ====================
app.post('/generate-dvh', uploadOrganMasks.array('organMasks', 10), async (req, res) => {
    try {
        const startTime = Date.now();
        console.log('[INFO] 请求开始时间:', new Date(startTime).toISOString());

        const { npyPath } = req.body;

        if (!npyPath) {
            throw new Error('缺少 NPY 文件路径');
        }

        if (!req.files || req.files.length === 0) {
            throw new Error('没有上传器官掩膜文件');
        }

        console.log('[DEBUG] 收到 NPY 文件路径:', npyPath);
        console.log('[DEBUG] 收到的器官掩膜文件:', req.files);

        const organMasksPaths = req.files.map(file => file.path);
        const organDir = path.join(__dirname, 'organ');
        await fs.ensureDir(organDir);

        // 解压文件
        for (const file of req.files) {
            const gzPath = path.join(organDir, file.filename);
            const uncompressedPath = path.join(organDir, path.basename(file.filename, '.gz'));

            console.log(`[DEBUG] 解压文件: ${gzPath} 到 ${uncompressedPath}`);
            try {
                await decompressNiiFile(gzPath, uncompressedPath);
                console.log(`[INFO] 解压成功: ${uncompressedPath}`);
            } catch (error) {
                console.error(`[ERROR] 解压失败: ${gzPath}, 错误信息: ${error.message}`);
                throw new Error('解压文件失败');
            }
        }

        const dvhScriptPath = path.join(__dirname, 'generate_dvh.py');
        const dvhOutputDir = path.join(__dirname, 'dvh');
        await fs.ensureDir(dvhOutputDir);
        console.log('[INFO] DVH图像输出目录：', dvhOutputDir);

        const masksList = organMasksPaths.join(',');
        const dvhCmd = `"${PYTHON_PATH}" "${dvhScriptPath}" --dose "${npyPath}" --masks "${masksList}" --outdir "${dvhOutputDir}"`;
        console.log('[DEBUG] 执行 Python 脚本的命令:', dvhCmd);

        let stdout, stderr;
        try {
            const { stdout: cmdStdout, stderr: cmdStderr } = await execAsync(dvhCmd);
            stdout = cmdStdout;
            stderr = cmdStderr;
            console.log('[INFO] Python 脚本输出:', stdout);
            if (stderr) {
                console.warn('[INFO] Python 脚本错误输出:', stderr);
            }
        } catch (error) {
            console.error('[ERROR] 执行 Python 脚本失败:', error);
            throw new Error('生成 DVH 图像失败');
        }

        const dvhImagePath = path.join(dvhOutputDir, 'dvh.png');
        console.log('[DEBUG] 生成的 DVH 图像完整路径:', dvhImagePath);

        const imageExists = await fs.pathExists(dvhImagePath);
        console.log('[DEBUG] 检查图像文件是否存在:', imageExists ? '存在' : '不存在');
        if (!imageExists) {
            console.error('[ERROR] DVH 图像未生成, 路径:', dvhImagePath);
            throw new Error('DVH 图像未生成');
        }

        const dvhImageRelPath = `/dvh/dvh.png?t=${Date.now()}`;

        console.log('[INFO] DVH图像生成路径：', dvhImageRelPath);

        const endTime = Date.now();
        console.log('[INFO] 请求结束时间:', new Date(endTime).toISOString());
        console.log('[INFO] 请求总时间: ', (endTime - startTime) / 1000, '秒');

        res.json({
            success: true,
            message: 'DVH 图像生成成功',
            dvhImagePath: dvhImageRelPath
        });

    } catch (err) {
        console.error('[ERROR] 生成 DVH 图像失败:', err.message);
        console.error('[ERROR] 堆栈: ', err.stack);
        res.status(500).json({
            success: false,
            message: '生成 DVH 图像失败',
            error: err.message
        });
    }
});


// 解压函数
function decompressNiiFile(inputPath, outputPath) {
    return new Promise((resolve, reject) => {
        const inputStream = fs.createReadStream(inputPath);
        const outputStream = fs.createWriteStream(outputPath);

        inputStream
            .pipe(zlib.createGunzip())  // 使用 Gunzip 解压
            .pipe(outputStream)
            .on('finish', () => resolve())
            .on('error', (err) => reject(err));
    });
};










// ==================== 启动服务器 ====================
const PORT = 3000;
// 配置全身评估输出目录
const WHOLEBODY_OUTPUT_DIR = path.join(__dirname, 'wholebody_output');
fs.ensureDirSync(WHOLEBODY_OUTPUT_DIR);

// ICRP数据路径
const ICRP_DATA_PATH = 'C:/my-app3/web/P110 data V1.2';

// 提供静态文件访问
app.use('/wholebody_output', express.static(WHOLEBODY_OUTPUT_DIR));

// ==================== API端点 ====================

/**
 * 0. 直接创建会话（无需上传CT文件）
 * POST /api/wholebody/create-session
 *
 * 请求参数（JSON body）:
 * - age: 患者年龄
 * - gender: 性别（male/female）
 * - height: 身高(cm)，默认170
 * - weight: 体重(kg)，默认70
 * - tumorLocation: 肿瘤/照射位置（brain/lung/liver/nasopharynx）
 * - niiPath: 已在服务器上的CT文件路径（可选）
 */
app.post('/api/wholebody/create-session', async (req, res) => {
    try {
        console.log('[全身评估] 收到直接创建会话请求');

        const {
            age,
            gender,
            height,
            weight,
            tumorLocation,
            exposureTime,
            niiPath
        } = req.body;

        if (!age || !gender) {
            return res.status(400).json({
                success: false,
                message: '缺少必需参数: age, gender'
            });
        }

        // 创建会话
        const sessionId = `session_${Date.now()}`;
        const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, sessionId);
        fs.ensureDirSync(sessionDir);

        console.log(`[全身评估] 创建会话: ${sessionId}`);

        // 保存患者信息（CT路径使用已有的服务器路径，可选）
        const patientInfo = {
            sessionId,
            age: parseInt(age),
            gender,
            height: parseFloat(height) || 170,
            weight: parseFloat(weight) || 70,
            tumor_location: tumorLocation || 'brain',
            exposure_time: parseFloat(exposureTime) || 30,
            ct_path: niiPath || null,
            timestamp: new Date().toISOString()
        };

        const patientInfoPath = path.join(sessionDir, 'patient_info.json');
        fs.writeJsonSync(patientInfoPath, patientInfo, { spaces: 2 });

        console.log(`[全身评估] 患者信息已保存: ${patientInfoPath}`);

        res.json({
            success: true,
            sessionId,
            message: '会话已创建',
            patientInfo: {
                ...patientInfo,
                ct_path: niiPath ? 'existing' : 'none'
            }
        });

    } catch (err) {
        console.error('[全身评估] 创建会话失败:', err);
        res.status(500).json({
            success: false,
            message: '创建会话失败',
            error: err.message
        });
    }
});

/**
 * 1. 上传患者信息和CT文件
 * POST /api/wholebody/upload-patient-ct
 *
 * 请求参数:
 * - ctFile: CT文件（可选）
 * - patientAge: 患者年龄
 * - patientGender: 性别（male/female）
 * - patientHeight: 身高(cm)
 * - patientWeight: 体重(kg)
 * - tumorLocation: 肿瘤位置（brain/lung/liver等）
 */
app.post('/api/wholebody/upload-patient-ct', uploadNii.single('ctFile'), async (req, res) => {
    try {
        console.log('[全身评估] 收到患者信息上传请求');
        
        const { 
            patientAge, 
            patientGender, 
            patientHeight, 
            patientWeight,
            tumorLocation 
        } = req.body;

        // 验证必需参数
        if (!patientAge || !patientGender || !patientHeight || !patientWeight) {
            return res.status(400).json({
                success: false,
                message: '缺少必需的患者参数'
            });
        }

        // 创建会话
        const sessionId = `session_${Date.now()}`;
        const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, sessionId);
        fs.ensureDirSync(sessionDir);

        console.log(`[全身评估] 创建会话: ${sessionId}`);

        // 处理CT文件（如果上传了）
        let ctPath = null;
        if (req.file) {
            const uploadedFolder = path.join(DIRS.UPLOADS, req.uploadFolder);
            const originalFilename = req.file.originalname;
            const gzPath = path.join(uploadedFolder, originalFilename);
            
            // 解压.nii.gz
            const niiPath = path.join(uploadedFolder, originalFilename.replace(/\.gz$/, ''));
            await compressing.gzip.uncompress(gzPath, niiPath);
            
            ctPath = niiPath;
            console.log(`[全身评估] CT文件已解压: ${ctPath}`);
        }

        // 保存患者信息
        const patientInfo = {
            sessionId,
            age: parseInt(patientAge),
            gender: patientGender,
            height: parseFloat(patientHeight),
            weight: parseFloat(patientWeight),
            tumor_location: tumorLocation || 'brain',
            ct_path: ctPath,
            timestamp: new Date().toISOString()
        };

        const patientInfoPath = path.join(sessionDir, 'patient_info.json');
        fs.writeJsonSync(patientInfoPath, patientInfo, { spaces: 2 });

        console.log(`[全身评估] 患者信息已保存: ${patientInfoPath}`);

        res.json({
            success: true,
            sessionId,
            message: '患者信息已保存',
            patientInfo: {
                ...patientInfo,
                ct_path: ctPath ? 'uploaded' : 'none'  // 不返回完整路径
            }
        });

    } catch (err) {
        console.error('[全身评估] 上传失败:', err);
        res.status(500).json({
            success: false,
            message: '上传失败',
            error: err.message
        });
    }
});

/**
 * 2. 运行全身风险评估
 * POST /api/wholebody/run-assessment
 * 
 * 请求参数:
 * - sessionId: 会话ID
 */
app.post('/api/wholebody/run-assessment', async (req, res) => {
    try {
        const { sessionId } = req.body;

        if (!sessionId) {
            return res.status(400).json({
                success: false,
                message: '缺少sessionId'
            });
        }

        const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, sessionId);

        if (!fs.existsSync(sessionDir)) {
            return res.status(404).json({
                success: false,
                message: '会话不存在'
            });
        }

        console.log(`[全身评估] 开始评估: ${sessionId}`);

        // 读取患者信息（验证）
        const patientInfoPath = path.join(sessionDir, 'patient_info.json');
        if (!fs.existsSync(patientInfoPath)) {
            return res.status(400).json({
                success: false,
                message: '患者信息文件不存在'
            });
        }

        // 查找MCNP计算生成的最新剂量文件（dose_results/*.npy）
        const doseResultsDir = path.join(__dirname, 'dose_results');
        let doseNpyPath = null;
        if (fs.existsSync(doseResultsDir)) {
            const doseFiles = fs.readdirSync(doseResultsDir)
                .filter(f => f.endsWith('.npy'))
                .map(f => ({
                    name: f,
                    fullPath: path.join(doseResultsDir, f),
                    time: fs.statSync(path.join(doseResultsDir, f)).mtime.getTime()
                }))
                .sort((a, b) => b.time - a.time);
            if (doseFiles.length > 0) {
                doseNpyPath = doseFiles[0].fullPath;
                console.log(`[全身评估] 找到MCNP剂量文件: ${doseNpyPath}`);
            }
        }
        if (!doseNpyPath) {
            console.log('[全身评估] 未找到MCNP剂量文件，将使用估算剂量（请先完成 CT→体模→MCNP计算 流程）');
        }

        // 调用Python脚本
        const pythonScript = path.join(__dirname, 'wholebody_risk_api.py');
        const pythonPath = 'D:/python.exe';
        let command = `"${pythonPath}" "${pythonScript}" --session-dir "${sessionDir}" --icrp-path "${ICRP_DATA_PATH}"`;
        if (doseNpyPath) {
            command += ` --dose-npy "${doseNpyPath}"`;
        }

        console.log(`[全身评估] 执行命令: ${command}`);

        // 执行评估（可能需要较长时间）
        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,  // 增加缓冲区到10MB
            env: {
                PYTHONIOENCODING: 'utf-8'  // ← 同时加上编码
            }
        });

        console.log('[全身评估] Python输出:', stdout);
        if (stderr) {
            console.error('[全身评估] Python错误:', stderr);
        }

        // 解析Python输出的JSON结果
        const resultMatch = stdout.match(/=== ASSESSMENT_RESULT ===([\s\S]*)=== END_RESULT ===/);
        let assessmentResult;
        
        if (resultMatch) {
            try {
                assessmentResult = JSON.parse(resultMatch[1].trim());
            } catch (parseErr) {
                console.error('[全身评估] 无法解析结果:', parseErr);
                throw new Error('评估结果解析失败');
            }
        } else {
            throw new Error('未找到评估结果');
        }

        if (!assessmentResult.success) {
            throw new Error(assessmentResult.error || '评估失败');
        }

        // 读取完整结果
        const resultsPath = path.join(sessionDir, 'complete_results.json');
        const completeResults = fs.readJsonSync(resultsPath);

        // 读取可视化数据
        const vizPath = path.join(sessionDir, 'visualization_data.json');
        const vizData = fs.readJsonSync(vizPath);

        console.log(`[全身评估] 评估完成: ${sessionId}`);

        res.json({
            success: true,
            message: '风险评估完成',
            sessionId,
            totalRisk: assessmentResult.total_risk,
            results: completeResults,
            visualization: vizData,
            files: {
                report: `/wholebody_output/${sessionId}/risk_assessment_report.txt`,
                reportJson: `/wholebody_output/${sessionId}/risk_assessment_report.json`,
                visualization: `/wholebody_output/${sessionId}/visualization_data.json`,
                completeResults: `/wholebody_output/${sessionId}/complete_results.json`
            }
        });

    } catch (err) {
        console.error('[全身评估] 评估失败:', err);
        res.status(500).json({
            success: false,
            message: '评估失败',
            error: err.message
        });
    }
});

/**
 * 3. 获取评估状态
 * GET /api/wholebody/assessment-status/:sessionId
 */
app.get('/api/wholebody/assessment-status/:sessionId', async (req, res) => {
    try {
        const { sessionId } = req.params;
        const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, sessionId);

        if (!fs.existsSync(sessionDir)) {
            return res.status(404).json({
                success: false,
                message: '会话不存在'
            });
        }

        const statusFile = path.join(sessionDir, 'status.json');
        
        if (fs.existsSync(statusFile)) {
            const status = fs.readJsonSync(statusFile);
            res.json({ 
                success: true, 
                status 
            });
        } else {
            res.json({ 
                success: true, 
                status: { 
                    step: 'pending',
                    progress: 0,
                    message: '等待开始'
                } 
            });
        }
    } catch (err) {
        console.error('[全身评估] 状态查询失败:', err);
        res.status(500).json({
            success: false,
            error: err.message
        });
    }
});

/**
 * 4. 获取可视化数据
 * GET /api/wholebody/visualization/:sessionId
 */
app.get('/api/wholebody/visualization/:sessionId', async (req, res) => {
    try {
        const { sessionId } = req.params;
        const vizPath = path.join(
            WHOLEBODY_OUTPUT_DIR, 
            sessionId,
            'visualization_data.json'
        );

        if (fs.existsSync(vizPath)) {
            const vizData = fs.readJsonSync(vizPath);
            res.json({ 
                success: true, 
                data: vizData 
            });
        } else {
            res.status(404).json({
                success: false,
                message: '可视化数据未找到'
            });
        }
    } catch (err) {
        console.error('[全身评估] 获取可视化数据失败:', err);
        res.status(500).json({
            success: false,
            error: err.message
        });
    }
});

/**
 * 5. 获取风险报告
 * GET /api/wholebody/report/:sessionId
 */
app.get('/api/wholebody/report/:sessionId', async (req, res) => {
    try {
        const { sessionId } = req.params;
        const { format } = req.query;  // 'txt' or 'json'
        
        const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, sessionId);
        
        let reportPath;
        if (format === 'json') {
            reportPath = path.join(sessionDir, 'risk_assessment_report.json');
        } else {
            reportPath = path.join(sessionDir, 'risk_assessment_report.txt');
        }

        if (fs.existsSync(reportPath)) {
            if (format === 'json') {
                const reportData = fs.readJsonSync(reportPath);
                res.json({ 
                    success: true, 
                    report: reportData 
                });
            } else {
                const reportText = fs.readFileSync(reportPath, 'utf-8');
                res.type('text/plain');
                res.send(reportText);
            }
        } else {
            res.status(404).json({
                success: false,
                message: '报告未找到'
            });
        }
    } catch (err) {
        console.error('[全身评估] 获取报告失败:', err);
        res.status(500).json({
            success: false,
            error: err.message
        });
    }
});

/**
 * 6. 列出所有评估会话
 * GET /api/wholebody/sessions
 */
app.get('/api/wholebody/sessions', async (req, res) => {
    try {
        const sessions = [];
        const sessionDirs = fs.readdirSync(WHOLEBODY_OUTPUT_DIR);

        for (const dir of sessionDirs) {
            if (dir.startsWith('session_')) {
                const sessionDir = path.join(WHOLEBODY_OUTPUT_DIR, dir);
                const patientInfoPath = path.join(sessionDir, 'patient_info.json');
                
                if (fs.existsSync(patientInfoPath)) {
                    const patientInfo = fs.readJsonSync(patientInfoPath);
                    sessions.push({
                        sessionId: dir,
                        timestamp: patientInfo.timestamp,
                        age: patientInfo.age,
                        gender: patientInfo.gender,
                        tumorLocation: patientInfo.tumor_location
                    });
                }
            }
        }

        // 按时间倒序排列
        sessions.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        res.json({
            success: true,
            sessions,
            total: sessions.length
        });

    } catch (err) {
        console.error('[全身评估] 获取会话列表失败:', err);
        res.status(500).json({
            success: false,
            error: err.message
        });
    }
});

// ==================== 清除会话文件 ====================
app.post('/clear-session', async (req, res) => {
    try {
        console.log('[清除会话] 开始清除所有工作文件...');
        const errors = [];

        // 1. 清除 uploads/ 下所有 nii_* 文件夹
        if (fs.existsSync(DIRS.UPLOADS)) {
            const uploadFolders = fs.readdirSync(DIRS.UPLOADS)
                .filter(f => f.startsWith('nii_'));
            for (const folder of uploadFolders) {
                try {
                    fs.removeSync(path.join(DIRS.UPLOADS, folder));
                    console.log(`[清除会话] 已删除上传文件夹: ${folder}`);
                } catch (e) { errors.push(`uploads/${folder}: ${e.message}`); }
            }
        }

        // 2. 清除 C:/i/ 目录中的MCNP输入文件及相关文件
        if (fs.existsSync(DIRS.INPUT)) {
            const inputFiles = fs.readdirSync(DIRS.INPUT);
            for (const file of inputFiles) {
                try {
                    fs.removeSync(path.join(DIRS.INPUT, file));
                } catch (e) { errors.push(`C:/i/${file}: ${e.message}`); }
            }
            console.log(`[清除会话] 已清除 C:/i/ 目录 (${inputFiles.length} 个文件)`);
        }

        // 3. 清除 C:/o/ 目录内容
        if (fs.existsSync(DIRS.OUTPUT)) {
            const outputFiles = fs.readdirSync(DIRS.OUTPUT);
            for (const file of outputFiles) {
                try {
                    fs.removeSync(path.join(DIRS.OUTPUT, file));
                } catch (e) { errors.push(`C:/o/${file}: ${e.message}`); }
            }
            console.log(`[清除会话] 已清除 C:/o/ 目录 (${outputFiles.length} 个文件)`);
        }

        // 4. 清除 dose_results/ 中的 .npy 文件
        const doseResultsDir = path.join(__dirname, 'dose_results');
        if (fs.existsSync(doseResultsDir)) {
            const npyFiles = fs.readdirSync(doseResultsDir).filter(f => f.endsWith('.npy'));
            for (const file of npyFiles) {
                try {
                    fs.removeSync(path.join(doseResultsDir, file));
                } catch (e) { errors.push(`dose_results/${file}: ${e.message}`); }
            }
            console.log(`[清除会话] 已清除 dose_results/ 中 ${npyFiles.length} 个 .npy 文件`);
        }

        // 5. 清除 dosepng/wholebody/ 目录
        const doseWholebodyDir = path.join(DIRS.DOSE_PNG, 'wholebody');
        if (fs.existsSync(doseWholebodyDir)) {
            try {
                fs.removeSync(doseWholebodyDir);
                fs.ensureDirSync(doseWholebodyDir);
                console.log('[清除会话] 已清除 dosepng/wholebody/ 目录');
            } catch (e) { errors.push(`dosepng/wholebody: ${e.message}`); }
        }

        // 6. 清除 wholebody_phantom/ 目录
        const phantomDir = path.join(__dirname, 'wholebody_phantom');
        if (fs.existsSync(phantomDir)) {
            try {
                fs.removeSync(phantomDir);
                console.log('[清除会话] 已清除 wholebody_phantom/ 目录');
            } catch (e) { errors.push(`wholebody_phantom: ${e.message}`); }
        }

        // 7. 清除 organ/ 目录内容
        const organDir = path.join(__dirname, 'organ');
        if (fs.existsSync(organDir)) {
            const organFiles = fs.readdirSync(organDir);
            for (const file of organFiles) {
                try {
                    fs.removeSync(path.join(organDir, file));
                } catch (e) { errors.push(`organ/${file}: ${e.message}`); }
            }
            console.log(`[清除会话] 已清除 organ/ 目录 (${organFiles.length} 个文件)`);
        }

        // 8. 清除 plus/ 和 dvh/ 目录内容
        for (const dirName of ['plus', 'dvh']) {
            const dirPath = path.join(__dirname, dirName);
            if (fs.existsSync(dirPath)) {
                const files = fs.readdirSync(dirPath);
                for (const file of files) {
                    try {
                        fs.removeSync(path.join(dirPath, file));
                    } catch (e) { errors.push(`${dirName}/${file}: ${e.message}`); }
                }
                console.log(`[清除会话] 已清除 ${dirName}/ 目录 (${files.length} 个文件)`);
            }
        }

        console.log('[清除会话] 清除完成');
        res.json({
            success: true,
            message: '会话文件已清除，可以开始新的处理流程',
            errors: errors.length > 0 ? errors : undefined
        });

    } catch (err) {
        console.error('[清除会话] 清除失败:', err.message);
        res.status(500).json({
            success: false,
            message: '清除会话文件失败',
            error: err.message
        });
    }
});

console.log('[全身评估] API端点已加载');
console.log(`  - POST /api/wholebody/create-session`);
console.log(`  - POST /api/wholebody/upload-patient-ct`);
console.log(`  - POST /api/wholebody/run-assessment`);
console.log(`  - GET  /api/wholebody/assessment-status/:sessionId`);
console.log(`  - GET  /api/wholebody/visualization/:sessionId`);
console.log(`  - GET  /api/wholebody/report/:sessionId`);
console.log(`  - GET  /api/wholebody/sessions`);
console.log(`  ICRP数据路径: ${ICRP_DATA_PATH}`);

// ==================== ICRP 标准体模对比 ====================

const ICRP_COMPARISON_OUTPUT_DIR = path.join(__dirname, 'icrp_comparison_output');
fs.ensureDirSync(ICRP_COMPARISON_OUTPUT_DIR);
app.use('/icrp_comparison_output', express.static(ICRP_COMPARISON_OUTPUT_DIR));

/**
 * POST /api/icrp-comparison
 * 用ICRP-110标准体模计算器官质量，与ICRP报告参考值对比
 * Body: { phantom_type: 'AM' | 'AF' }
 */
app.post('/api/icrp-comparison', async (req, res) => {
    const { phantom_type = 'AM' } = req.body;
    if (!['AM', 'AF'].includes(phantom_type.toUpperCase())) {
        return res.status(400).json({ success: false, message: '体模类型必须为 AM 或 AF' });
    }

    const pt = phantom_type.toUpperCase();
    const timestamp = Date.now();
    const chartFile = path.join(ICRP_COMPARISON_OUTPUT_DIR, `comparison_${pt}_${timestamp}.png`);
    const jsonFile = path.join(ICRP_COMPARISON_OUTPUT_DIR, `comparison_${pt}_${timestamp}.json`);

    // 动态获取ICRP数据路径：优先使用与index.js同级的解压目录，否则回退到Windows路径
    const localDataDir = path.join(__dirname, '..', 'P110 data V1.2');
    const icrcDataDir = fs.existsSync(localDataDir) ? localDataDir : ICRP_DATA_PATH;

    const pythonScript = path.join(__dirname, 'icrp_comparison.py');
    const pythonPath = PYTHON_PATH;

    const command = `"${pythonPath}" "${pythonScript}" --phantom ${pt} --data-dir "${icrcDataDir}" --chart "${chartFile}" --json-output "${jsonFile}"`;

    log(`[ICRP对比] 开始对比 ${pt} 体模...`);
    log(`[ICRP对比] 命令: ${command}`);

    try {
        const { stdout, stderr } = await execAsync(command, { timeout: 600000 });
        if (stdout) log(`[ICRP对比] stdout: ${stdout}`);
        if (stderr) log(`[ICRP对比] stderr: ${stderr}`);

        if (!fs.existsSync(jsonFile)) {
            throw new Error('Python脚本未生成结果JSON文件');
        }

        const result = JSON.parse(fs.readFileSync(jsonFile, 'utf-8'));
        const chartUrl = fs.existsSync(chartFile)
            ? `/icrp_comparison_output/${path.basename(chartFile)}`
            : null;

        res.json({
            success: true,
            phantom_type: pt,
            chart_url: chartUrl,
            data: result,
        });
    } catch (err) {
        log(`[ICRP对比] 失败: ${err.message}`, 'error');
        res.status(500).json({
            success: false,
            message: 'ICRP对比计算失败',
            error: err.message,
        });
    }
});

console.log('[ICRP对比] API端点已加载: POST /api/icrp-comparison');

// ==================== 器官轮廓叠加 ====================

// multer: 接收上传的器官 mask (.nii / .nii.gz)
const uploadContourMasks = multer({
    storage: multer.diskStorage({
        destination: (req, file, cb) => {
            const dir = path.join(__dirname, 'contour_masks');
            fs.ensureDirSync(dir);
            cb(null, dir);
        },
        filename: (req, file, cb) => cb(null, file.originalname)
    })
});

/**
 * 公共辅助：调用 contour_overlay.py，用临时文件传路径（避免 Windows 命令行 8191 字符限制）。
 * @param {string}   ctPath     CT NIfTI 文件路径
 * @param {string[]} maskPaths  mask 文件路径数组
 * @param {string[]} organNames 器官名称数组
 * @param {string}   outDir     输出目录
 */
async function runContourOverlay(ctPath, maskPaths, organNames, outDir) {
    const tmpMasks = path.join(outDir, '_masks.txt');
    const tmpNames = path.join(outDir, '_names.txt');
    await fs.writeFile(tmpMasks, maskPaths.join('\n'), 'utf8');
    await fs.writeFile(tmpNames, organNames.join('\n'), 'utf8');

    const scriptPath = path.join(__dirname, 'contour_overlay.py');
    const cmd = `"${PYTHON_PATH}" "${scriptPath}" --ct "${ctPath}" --masks-file "${tmpMasks}" --names-file "${tmpNames}" --outdir "${outDir}"`;
    console.log(`[轮廓叠加] 调用脚本，共 ${maskPaths.length} 个 mask`);

    const { stdout, stderr } = await execAsync(cmd, { timeout: 600000 });
    if (stderr) console.warn('[轮廓叠加] stderr:', stderr);

    const lines = stdout.trim().split('\n');
    const jsonLine = lines.reverse().find(l => l.startsWith('{'));
    if (!jsonLine) throw new Error('contour_overlay.py 未返回 JSON');
    const result = JSON.parse(jsonLine);
    if (!result.success) throw new Error(result.error || '轮廓生成失败');

    // 清理临时文件
    await fs.remove(tmpMasks).catch(() => {});
    await fs.remove(tmpNames).catch(() => {});

    return result;
}

/**
 * POST /generate-contour-slices
 * 接收上传的器官 mask 文件（手动上传模式）
 */
app.post('/generate-contour-slices', uploadContourMasks.array('masks', 20), async (req, res) => {
    try {
        const { ctPath, organNames } = req.body;
        if (!ctPath) throw new Error('缺少 ctPath 参数');
        if (!req.files || req.files.length === 0) throw new Error('没有上传器官 mask 文件');

        // 解压 .nii.gz → .nii
        const niiPaths = [];
        for (const file of req.files) {
            const filePath = file.path;
            if (filePath.endsWith('.gz')) {
                const unzipped = filePath.slice(0, -3);
                await new Promise((resolve, reject) => {
                    const input = require('fs').createReadStream(filePath);
                    const output = require('fs').createWriteStream(unzipped);
                    const gunzip = zlib.createGunzip();
                    input.pipe(gunzip).pipe(output).on('finish', resolve).on('error', reject);
                });
                niiPaths.push(unzipped);
            } else {
                niiPaths.push(filePath);
            }
        }

        const names = organNames
            ? organNames.split(',').map(n => n.trim())
            : niiPaths.map((_, i) => `Organ${i + 1}`);

        const outDir = path.join(__dirname, 'contour_slices');
        await fs.ensureDir(outDir);
        await runContourOverlay(ctPath, niiPaths, names, outDir);

        const buildUrls = async (view) => {
            const viewDir = path.join(outDir, view);
            const files = (await fs.readdir(viewDir)).sort().filter(f => f.endsWith('.png'));
            return files.map(f => `/contour_slices/${view}/${f}`);
        };
        const [axial, coronal, sagittal] = await Promise.all([
            buildUrls('axial'), buildUrls('coronal'), buildUrls('sagittal')
        ]);
        res.json({ success: true, axial, coronal, sagittal });

    } catch (err) {
        console.error('[轮廓叠加] 失败:', err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

/**
 * POST /generate-contour-slices-by-path
 * 直接传服务器端路径（自动勾画后使用）
 */
app.post('/generate-contour-slices-by-path', async (req, res) => {
    try {
        const { ctPath, maskPaths, organNames } = req.body;
        if (!ctPath) throw new Error('缺少 ctPath');
        if (!maskPaths || maskPaths.length === 0) throw new Error('缺少 maskPaths');

        const names = organNames
            ? organNames.split(',').map(n => n.trim())
            : maskPaths.map((_, i) => `Organ${i + 1}`);

        const outDir = path.join(__dirname, 'contour_slices');
        await fs.ensureDir(outDir);
        await runContourOverlay(ctPath, maskPaths, names, outDir);

        const buildUrls = async (view) => {
            const viewDir = path.join(outDir, view);
            const files = (await fs.readdir(viewDir)).sort().filter(f => f.endsWith('.png'));
            return files.map(f => `/contour_slices/${view}/${f}`);
        };
        const [axial, coronal, sagittal] = await Promise.all([
            buildUrls('axial'), buildUrls('coronal'), buildUrls('sagittal')
        ]);
        res.json({ success: true, axial, coronal, sagittal });

    } catch (err) {
        console.error('[轮廓叠加(路径模式)] 失败:', err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

// 静态托管轮廓叠加图
app.use('/contour_slices', express.static(path.join(__dirname, 'contour_slices')));

// ==================== 自动勾画 ====================

/**
 * POST /auto-segment
 * body (JSON): { ctPath }
 * 返回: { success, organs: [...], maskFiles: [...] }
 *       或 { success: false, error, install_cmd }
 */
app.post('/auto-segment', async (req, res) => {
    try {
        const { ctPath } = req.body;
        if (!ctPath) throw new Error('缺少 ctPath 参数');

        const outDir = path.join(__dirname, 'auto_seg_output');
        await fs.ensureDir(outDir);

        const scriptPath = path.join(__dirname, 'auto_segment.py');
        const cmd = `"${PYTHON_PATH}" "${scriptPath}" --ct "${ctPath}" --outdir "${outDir}" --fast`;
        console.log('[自动勾画] 执行:', cmd);

        const { stdout, stderr } = await execAsync(cmd, { timeout: 600000 });
        if (stderr) console.warn('[自动勾画] stderr:', stderr);

        const lines = stdout.trim().split('\n');
        const jsonLine = lines.reverse().find(l => l.startsWith('{'));
        if (!jsonLine) throw new Error('Python 脚本未返回 JSON');
        const result = JSON.parse(jsonLine);

        res.json(result);

    } catch (err) {
        console.error('[自动勾画] 失败:', err.message);
        res.status(500).json({ success: false, error: err.message });
    }
});

console.log('[轮廓功能] API端点已加载:');
console.log('  - POST /generate-contour-slices');
console.log('  - POST /auto-segment');

app.listen(PORT, () => {
    log(`服务器已启动: http://localhost:${PORT}`);
});