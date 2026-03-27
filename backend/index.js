const express = require('express');
const multer = require('multer');
const fs = require('fs-extra');
const path = require('path');
const { exec, spawn } = require('child_process');
const util = require('util');
const cors = require('cors');
const compressing = require('compressing');
const execAsync = util.promisify(exec);
const app = express();

// MCNP 实时进度状态
const mcnpState = {
  running: false,
  progress: 0,
  logs: [],
  total: 0,
  completed: 0
};
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
app.use('/wholebody_phantom', express.static(path.join(__dirname, 'wholebody_phantom')));

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

        // 提取 CT 元数据（体素大小、物理尺寸、中心坐标）
        let ctMetadata = null;
        try {
            const metaScript = path.join(__dirname, 'ct_metadata.py');
            const { stdout: metaOut } = await execAsync(`"${PYTHON_PATH}" "${metaScript}" "${niiPath}"`);
            ctMetadata = JSON.parse(metaOut.trim());
            console.log('CT metadata extracted:', ctMetadata);
        } catch (metaErr) {
            console.warn('CT metadata extraction failed (non-fatal):', metaErr.message);
        }

        // 响应前端
        res.json({
            success: true,
            message: '.nii.gz 文件处理成功，MCNP 输入文件、.npy 文件与切片生成完毕',
            folderName: req.uploadFolder,
            niiPath,
            npyPath,
            ctMetadata,
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

        // 生成全身体模可视化切片图像（异步，不阻塞主响应）
        const phantomPreviewDir = path.join(outputDir, 'preview_slices');
        const phantomPreviewScript = path.join(__dirname, 'phantom_preview.py');
        const phantomPreviewResult = { axial: [], coronal: [], sagittal: [] };

        try {
            const phantomType = gender === 'female' ? 'AF' : 'AM';
            const previewCmd = `"${PYTHON_PATH}" "${phantomPreviewScript}" "${phantomPreviewDir}" --type "${phantomType}"`;
            const { stdout: pvOut } = await execAsync(previewCmd, {
                maxBuffer: 20 * 1024 * 1024,
                env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
            });
            const pvJson = JSON.parse(pvOut.trim().split('\n').pop());
            if (pvJson.success) {
                for (const view of ['axial', 'coronal', 'sagittal']) {
                    const vDir = path.join(phantomPreviewDir, view);
                    if (fs.existsSync(vDir)) {
                        const files = fs.readdirSync(vDir).sort();
                        phantomPreviewResult[view] = files.map(f =>
                            `/wholebody_phantom/preview_slices/${view}/${f}`
                        );
                    }
                }
                console.log(`体模预览切片生成完成: axial=${phantomPreviewResult.axial.length}, coronal=${phantomPreviewResult.coronal.length}, sagittal=${phantomPreviewResult.sagittal.length}`);
            }
        } catch (pvErr) {
            console.warn('体模预览切片生成失败（非致命）:', pvErr.message);
        }

        res.json({
            success: true,
            message: '全身体模构建完成',
            phantomDir: outputDir,
            mcnpInputFile: mcnpInputFile,
            mcnpInputFileInI: targetFilePath,
            mcnpFileName: targetFileName,
            anatomicalRegion: anatomicalRegion,
            phantomSlices: phantomPreviewResult
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

        const {
            axialImagePath,
            source_position, source_direction, beam_radius,
            phantom_type, tumor_position, tumor_radius
        } = req.body || {};

        if (source_position) console.log(`剂量图生成参数 - 源位置: [${source_position.join(', ')}] cm`);
        if (tumor_position) console.log(`剂量图生成参数 - 肿瘤位置: [${tumor_position.join(', ')}] cm, 半径: ${tumor_radius} cm`);

        // 剂量数据目录 - 检查多个可能的位置
        const dosePngDir = DIRS.DOSE_PNG;
        const doseResultsDir = path.join(__dirname, 'dose_results');
        
        // ===== 步骤1: 查找剂量文件（.npy） =====
        let doseNpyPath = null;
        let doseFiles = [];
        
        // 优先在dose_results中查找（run_batch.py生成的位置）
        if (fs.existsSync(doseResultsDir)) {
            // 排除 EMESH 辅助文件（_ebounds.npy, _bin0.npy 等），只取主剂量文件
            doseFiles = fs.readdirSync(doseResultsDir).filter(f =>
                f.endsWith('.npy') && !f.includes('_ebounds') && !/_bin\d+\.npy$/.test(f));
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
                doseFiles = fs.readdirSync(dosePngDir).filter(f =>
                    f.endsWith('.npy') && !f.includes('_ebounds') && !/_bin\d+\.npy$/.test(f));
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
        const { visibleOrgans } = req.body;
        const dosePngDir = DIRS.DOSE_PNG;
        const doseResultsDir = path.join(__dirname, 'dose_results');

        // 查找剂量文件（与 generate-wholebody-dose-map 相同逻辑）
        let doseNpyPath = null;
        if (fs.existsSync(doseResultsDir)) {
            const doseFiles = fs.readdirSync(doseResultsDir).filter(f =>
                f.endsWith('.npy') && !f.includes('_ebounds') && !/_bin\d+\.npy$/.test(f));
            if (doseFiles.length > 0) {
                const sorted = doseFiles.map(f => ({
                    name: f, time: fs.statSync(path.join(doseResultsDir, f)).mtime.getTime()
                })).sort((a, b) => b.time - a.time);
                doseNpyPath = path.join(doseResultsDir, sorted[0].name);
            }
        }
        if (!doseNpyPath && fs.existsSync(dosePngDir)) {
            const doseFiles = fs.readdirSync(dosePngDir).filter(f =>
                f.endsWith('.npy') && !f.includes('_ebounds') && !/_bin\d+\.npy$/.test(f));
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

        // visibleOrgans 为空字符串表示全消（不画任何轮廓）
        const visibleOrgansArg = (visibleOrgans !== undefined)
            ? ` "--visible-organs=${(visibleOrgans || '').trim()}"`
            : '';
        const command = `"${PYTHON_PATH}" "${doseScript}" "${doseNpyPath}" "${outputDir}" "${refNiiPath}"${visibleOrgansArg}`;
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



// 返回当前 MCNP 计算进度和日志（供前端轮询）
app.get('/mcnp-progress', (req, res) => {
    const newLogs = mcnpState.logs.splice(0); // 取走所有新日志后清空缓冲
    res.json({
        running: mcnpState.running,
        progress: mcnpState.progress,
        logs: newLogs,
        completed: mcnpState.completed,
        total: mcnpState.total
    });
});

app.post('/run-mcnp-computation', async (req, res) => {
    try {
        const inputDir = DIRS.INPUT;
        const outputDir = DIRS.OUTPUT;
        const batchFile = 'ccmd.bat';

        // 接收前端传来的剂量组分参数设置
        const {
            source_position, source_direction, beam_radius,
            phantom_type, tumor_position, tumor_radius,
            height_cm, weight_kg, intensity, cbe_rbe, boron_conc
        } = req.body || {};

        console.log('MCNP computation request received');
        if (source_position) console.log(`源位置: [${source_position.join(', ')}] cm, 束流半径: ${beam_radius} cm`);
        if (tumor_position) console.log(`肿瘤位置: [${tumor_position.join(', ')}] cm, 半径: ${tumor_radius} cm`);
        if (phantom_type) console.log(`体模类型: ${phantom_type}, 身高: ${height_cm}cm, 体重: ${weight_kg}kg`);
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

        // 【修复】在运行MCNP前，将前端传来的源参数写入.inp文件
        // 原始.inp由ct_phantom_fusion.py生成，源位置硬编码在体模内部，
        // 需替换为用户在可视化界面设置的源位置和束流半径
        if (source_position && source_position.length === 3) {
            console.log('Updating MCNP input files with user-specified source parameters...');
            for (const filePath of sortedInputFiles) {
                const fullFilePath = path.join(inputDir, filePath);
                try {
                    let content = await fs.readFile(fullFilePath, 'utf8');

                    // 从RPP边界卡解析体模绝对尺寸: "20 RPP 0 {x_max}  0 {y_max}  0 {z_max}"
                    const rppMatch = content.match(/20\s+RPP\s+0\s+([\d.]+)\s+0\s+([\d.]+)\s+0\s+([\d.]+)/);
                    if (!rppMatch) {
                        console.warn(`[sdef update] RPP card not found in ${filePath}, skipping`);
                        continue;
                    }

                    const x_max = parseFloat(rppMatch[1]);
                    const y_max = parseFloat(rppMatch[2]);
                    const z_max = parseFloat(rppMatch[3]);

                    // 前端坐标以体模中心为原点，转换为MCNP绝对坐标
                    const cx = x_max / 2, cy = y_max / 2, cz = z_max / 2;
                    const sp = source_position;
                    const sd = source_direction || [0, 0, -1];
                    const br = beam_radius || 5.0;
                    const sx = Math.max(0.001, Math.min(cx + sp[0], x_max - 0.001));
                    const sy = Math.max(0.001, Math.min(cy + sp[1], y_max - 0.001));
                    // 源Z坐标钳位至容器RPP内部（[0.001, z_max-0.001]），
                    // 防止源位于 imp:n=0 的外部虚空区导致 MCNP fatal error
                    const sz_raw = cz + sp[2];
                    const sz = Math.max(0.001, Math.min(sz_raw, z_max - 0.001));
                    if (sz_raw !== sz) {
                        console.warn(`[sdef update] source z=${sz_raw.toFixed(3)} outside container [0, ${z_max}], clamped to ${sz.toFixed(3)}`);
                    }

                    // 替换sdef行（源位置、束流方向）
                    content = content.replace(
                        /^sdef\s+pos=.*$/m,
                        `sdef pos=${sx.toFixed(3)} ${sy.toFixed(3)} ${sz.toFixed(3)} axs=${sd[0]} ${sd[1]} ${sd[2]} ext=0 rad=d1 erg=0.025e-3 par=1`
                    );
                    // 替换si1束流半径行
                    content = content.replace(
                        /^si1\s+0\s+[\d.]+/m,
                        `si1 0 ${br}`
                    );

                    await fs.writeFile(fullFilePath, content, 'utf8');
                    console.log(`[sdef update] ${filePath}: pos=[${sx.toFixed(2)}, ${sy.toFixed(2)}, ${sz.toFixed(2)}] axs=[${sd}] radius=${br}`);
                } catch (updateErr) {
                    console.error(`[sdef update] Failed to update ${filePath}: ${updateErr.message}`);
                }
            }
        } else {
            console.warn('[sdef update] source_position not provided, using existing .inp source definition');
        }

        // 【修复】将前端设置的肿瘤位置和半径注入MCNP lattice fill array
        // 原始.inp由ct_phantom_fusion.py生成，没有肿瘤区域（material 900）。
        // 若不注入，MCNP计算的剂量峰值将出现在束流入射点（胸腔表面），
        // 而非肿瘤位置——即用户在可视化中看到的错误现象。
        if (tumor_position && tumor_position.length === 3 && tumor_radius) {
            console.log('[tumor inject] 开始向 .inp 文件注入肿瘤区域...');
            const injectScript = path.join(__dirname, 'inject_tumor_to_inp.py');
            for (const filePath of sortedInputFiles) {
                const fullFilePath = path.join(inputDir, filePath);
                try {
                    const pt = phantom_type || 'AM';
                    const injectCmd = [
                        PYTHON_PATH, injectScript, fullFilePath,
                        '--tx', tumor_position[0].toString(),
                        '--ty', tumor_position[1].toString(),
                        '--tz', tumor_position[2].toString(),
                        '--radius', tumor_radius.toString(),
                        '--phantom-type', pt
                    ];
                    const injectResult = await new Promise((resolve, reject) => {
                        const proc = spawn(injectCmd[0], injectCmd.slice(1), { cwd: __dirname });
                        let out = '', err = '';
                        proc.stdout.on('data', d => { out += d.toString(); });
                        proc.stderr.on('data', d => { err += d.toString(); });
                        proc.on('close', code => resolve({ code, out, err }));
                        proc.on('error', reject);
                    });
                    if (injectResult.code === 0) {
                        // 解析最后一行 JSON 结果
                        const lastLine = injectResult.out.trim().split('\n').pop();
                        try {
                            const injectJson = JSON.parse(lastLine);
                            console.log(`[tumor inject] ${filePath}: ${injectJson.tumor_voxels_injected} 个肿瘤体素已注入`);
                            mcnpState.logs.push(`[肿瘤注入] ${injectJson.tumor_voxels_injected} 个体素注入为材料900 (B-10 loaded)`);
                        } catch (_) {
                            console.log(`[tumor inject] ${filePath}: 注入完成`);
                        }
                        if (injectResult.out) console.log(`[tumor inject stdout] ${injectResult.out}`);
                    } else {
                        console.error(`[tumor inject] ${filePath} 失败 (退出码: ${injectResult.code})`);
                        if (injectResult.err) console.error(`[tumor inject stderr] ${injectResult.err}`);
                    }
                } catch (injectErr) {
                    console.error(`[tumor inject] ${filePath} 出错: ${injectErr.message}`);
                }
            }
        } else {
            console.warn('[tumor inject] tumor_position 未提供，跳过肿瘤区域注入');
        }

        // 初始化进度状态
        mcnpState.running = true;
        mcnpState.progress = 0;
        mcnpState.logs = [];
        mcnpState.total = sortedInputFiles.length;
        mcnpState.completed = 0;

        // 辅助函数：用 spawn 执行单个文件，实时收集日志
        const runWithSpawn = (fullFilePath, fileName) => new Promise((resolve, reject) => {
            const proc = spawn(PYTHON_PATH, ['run_batch.py', fullFilePath], {
                cwd: __dirname
            });
            let stdoutBuf = Buffer.alloc(0);
            let stderrBuf = Buffer.alloc(0);

            proc.stdout.on('data', (chunk) => {
                stdoutBuf = Buffer.concat([stdoutBuf, chunk]);
                const lines = chunk.toString('utf8').replace(/\uFFFD/g, '?').split(/\r?\n/);
                lines.forEach(line => {
                    if (line.trim()) {
                        mcnpState.logs.push(`[${fileName}] ${line}`);
                        console.log(`[MCNP stdout] ${line}`);
                    }
                });
            });
            proc.stderr.on('data', (chunk) => {
                stderrBuf = Buffer.concat([stderrBuf, chunk]);
                const lines = chunk.toString('utf8').replace(/\uFFFD/g, '?').split(/\r?\n/);
                lines.forEach(line => {
                    if (line.trim()) {
                        mcnpState.logs.push(`[${fileName}] WARN: ${line}`);
                    }
                });
            });
            proc.on('close', (code) => {
                const stdoutStr = stdoutBuf.toString('utf8').replace(/\uFFFD/g, '?');
                const stderrStr = stderrBuf.toString('utf8').replace(/\uFFFD/g, '?');
                resolve({ file: fileName, stdout: stdoutStr, stderr: stderrStr, code });
            });
            proc.on('error', reject);
        });

        // 执行 MCNP 计算
        const results = [];
        for (const filePath of sortedInputFiles) {
            const fullFilePath = path.join(inputDir, filePath);
            console.log(`Running MCNP calculation for file: ${fullFilePath}`);
            mcnpState.logs.push(`开始处理: ${filePath}`);

            const result = await runWithSpawn(fullFilePath, filePath);
            results.push(result);

            mcnpState.completed += 1;
            mcnpState.progress = Math.round((mcnpState.completed / mcnpState.total) * 95);
            mcnpState.logs.push(`完成: ${filePath} (退出码: ${result.code})`);
        }

        mcnpState.progress = 100;
        mcnpState.running = false;

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
        mcnpState.running = false;
        mcnpState.logs.push(`计算出错: ${err.message}`);
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

// ==================== 中子AP ICRP剂量对比 ====================

const NEUTRON_ICRP_OUTPUT_DIR = path.join(__dirname, 'neutron_icrp_ap_results');
fs.ensureDirSync(NEUTRON_ICRP_OUTPUT_DIR);
app.use('/neutron_icrp_ap_results', express.static(NEUTRON_ICRP_OUTPUT_DIR));

/**
 * POST /api/neutron-icrp-dose-comparison
 * 生成中子AP照射ICRP参考条件全量剂量转换系数对比图表
 * Body: { phantom_type: 'AM' | 'AF' }
 * 返回5张图表URL + JSON摘要数据
 */
app.post('/api/neutron-icrp-dose-comparison', async (req, res) => {
    const { phantom_type = 'AM' } = req.body;
    if (!['AM', 'AF'].includes(phantom_type.toUpperCase())) {
        return res.status(400).json({ success: false, message: '体模类型必须为 AM 或 AF' });
    }

    const pt = phantom_type.toUpperCase();
    const outDir = NEUTRON_ICRP_OUTPUT_DIR;
    const pythonScript = path.join(__dirname, 'neutron_icrp_dose_comparison.py');
    const pythonPath = PYTHON_PATH;

    const command = `"${pythonPath}" "${pythonScript}" --phantom ${pt} --output-dir "${outDir}"`;

    log(`[中子ICRP] 开始生成 ${pt} 体模 AP 剂量对比图表...`);

    try {
        const { stdout, stderr } = await execAsync(command, {
            timeout: 120000,
            env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        });
        if (stdout) log(`[中子ICRP] stdout: ${stdout}`);
        if (stderr) log(`[中子ICRP] stderr: ${stderr}`);

        // 读取生成的JSON数据
        const jsonFile = path.join(outDir, `neutron_AP_${pt}_all_quantities.json`);
        if (!fs.existsSync(jsonFile)) {
            throw new Error('Python脚本未生成JSON结果文件');
        }
        const data = JSON.parse(fs.readFileSync(jsonFile, 'utf-8'));

        // 构建5张图的URL
        const figNames = [
            `fig1_neutron_AP_${pt}_effective_dose_curve.png`,
            `fig2_neutron_AP_${pt}_organ_HT_curves.png`,
            `fig3_neutron_AP_${pt}_organ_bar_comparison.png`,
            `fig4_neutron_AP_${pt}_effective_dose_verification.png`,
            `fig5_neutron_AP_${pt}_wT_contribution_stack.png`,
        ];
        const figTitles = [
            '有效剂量转换系数 E/Φ — 全能量曲线（31个能量点）',
            '各器官当量剂量转换系数 HT/Φ — 多线曲线图',
            '器官 HT/Φ 柱状图对比（热中子 / 10 keV / 1 MeV）',
            '有效剂量验证：ICRP116表格值 vs Σ(wT·HT/Φ)',
            '各器官 wT 加权贡献堆积面积图',
        ];

        const charts = figNames.map((fname, i) => ({
            title: figTitles[i],
            url: fs.existsSync(path.join(outDir, fname))
                ? `/neutron_icrp_ap_results/${fname}`
                : null,
        }));

        res.json({
            success: true,
            phantom_type: pt,
            charts,
            summary: {
                n_energies: data.effective_dose.n_points,
                n_organs: Object.keys(data.organ_ht).length,
                source: data.source,
                geometry: data.geometry,
                radiation: data.radiation,
            },
            effective_dose: data.effective_dose,
            verify: data.effective_dose_verify,
        });
    } catch (err) {
        log(`[中子ICRP] 失败: ${err.message}`, 'error');
        res.status(500).json({
            success: false,
            message: '中子ICRP剂量对比生成失败',
            error: err.message,
        });
    }
});

console.log('[中子ICRP] API端点已加载: POST /api/neutron-icrp-dose-comparison');

// ==================== BEIR VII 验证 ====================

/**
 * GET /api/beir7-validation
 * 运行 validate_beir7.py --json，返回验证结果
 */
app.get('/api/beir7-validation', async (req, res) => {
    try {
        const pythonPath = process.platform === 'win32' ? 'python' : 'python3';
        const script = path.join(__dirname, 'validate_beir7.py');
        const { stdout, stderr } = await new Promise((resolve, reject) => {
            const { exec } = require('child_process');
            exec(`"${pythonPath}" "${script}" --json`, { timeout: 30000, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }, (err, stdout, stderr) => {
                if (err) reject(err);
                else resolve({ stdout, stderr });
            });
        });
        const data = JSON.parse(stdout);
        res.json({ success: true, data });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

console.log('[BEIR VII验证] API端点已加载: GET /api/beir7-validation');

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

// ==================== 剂量组分计算 ====================

/**
 * 通用辅助：用 spawn + stdin 调用 Python 脚本，避免命令行 JSON 转义问题
 */
function spawnPython(scriptPath, inputObj, timeoutMs) {
    return new Promise((resolve, reject) => {
        // PYTHONUTF8=1 强制 Python stdout 使用 UTF-8，避免 Windows GBK 编码错误
        const env = Object.assign({}, process.env, { PYTHONUTF8: '1' });
        const proc = spawn(PYTHON_PATH, [scriptPath], { env });
        let stdout = '';
        let stderr = '';
        const timer = setTimeout(() => {
            proc.kill();
            reject(new Error('Python 脚本超时'));
        }, timeoutMs);

        proc.stdout.on('data', d => { stdout += d; });
        proc.stderr.on('data', d => { stderr += d; });
        proc.on('close', () => {
            clearTimeout(timer);
            if (stderr) console.warn(`[spawnPython] stderr: ${stderr.slice(0, 300)}`);
            const raw = stdout.trim();
            // 找到第一个 '{' 开始位置，截取完整 JSON（支持多行缩进输出）
            const jsonStart = raw.indexOf('{');
            if (jsonStart === -1) {
                reject(new Error(`Python 脚本未返回 JSON。stdout: ${raw.slice(0, 200)}`));
                return;
            }
            try { resolve(JSON.parse(raw.slice(jsonStart))); }
            catch (e) { reject(new Error(`JSON 解析失败: ${e.message}\nraw: ${raw.slice(jsonStart, jsonStart + 120)}`)); }
        });
        proc.on('error', err => { clearTimeout(timer); reject(err); });

        // 通过 stdin 传递参数，完全避免 shell 转义问题
        proc.stdin.write(JSON.stringify(inputObj));
        proc.stdin.end();
    });
}

/**
 * POST /dose-components/calculate
 */
app.post('/dose-components/calculate', async (req, res) => {
    try {
        console.log('[剂量组分] 执行计算...');
        const scriptPath = path.join(__dirname, 'dose_component_calculator.py');
        const result = await spawnPython(scriptPath, req.body || {}, 60000);
        res.json(result);
    } catch (err) {
        console.error('[剂量组分计算] 失败:', err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

/**
 * POST /dose-components/validate
 */
app.post('/dose-components/validate', async (req, res) => {
    try {
        console.log('[剂量组分验证] 运行三级验证...');
        const scriptPath = path.join(__dirname, 'validate_dose_components.py');
        const result = await spawnPython(scriptPath, req.body || {}, 120000);
        res.json(result);
    } catch (err) {
        console.error('[剂量组分验证] 失败:', err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

console.log('[剂量组分] API端点已加载:');
console.log('  - POST /dose-components/calculate');
console.log('  - POST /dose-components/validate');

// ═══════════════════════════════════════════════════════
// ICRP-116 光子剂量系数 AP 验证接口
// ═══════════════════════════════════════════════════════

// 任务状态（内存中，重启后重置）
const icrp116Job = {
    running: false,
    pid: null,
    proc: null,
    startTime: null,
    logs: [],
    completed: false,
    failed: false,
    currentCase: null,
    doneEnergies: [],
    // 性别平均 (AM+AF) 扩展字段
    sexAvg: false,
    phase: 'AM',          // 'AM' | 'AF'
    afCurrentCase: null,
    afDoneEnergies: [],
};

const ICRP116_INP_DIR     = path.join(__dirname, 'icrp_validation', 'mcnp_inputs');
const ICRP116_OUT_DIR     = path.join(__dirname, 'icrp_validation', 'mcnp_outputs');
const ICRP116_AF_OUT_DIR  = ICRP116_OUT_DIR + '_AF';
const ICRP116_AF_MASK     = path.join(__dirname, 'icrp_validation', 'organ_mask_127x63x111_AF.npy');
const ICRP116_AF_ZIP      = path.join(__dirname, '..', 'P110 data V1.2', 'AF.zip');
const ICRP116_SCRIPT      = path.join(__dirname, 'mcnp_icrp_step2b_run_mcnp.py');

/**
 * 清空 mcnp_outputs 目录中的所有计算结果文件（fluence*.npy、*_f6doses.json、*.csv、*.png 等）。
 * 保留目录本身；任务运行时拒绝执行。
 */
function clearIcrp116Outputs() {
    const fs = require('fs');
    try {
        if (!fs.existsSync(ICRP116_OUT_DIR)) {
            fs.mkdirSync(ICRP116_OUT_DIR, { recursive: true });
            return { cleared: 0 };
        }
        const files = fs.readdirSync(ICRP116_OUT_DIR);
        let cleared = 0;
        for (const f of files) {
            fs.unlinkSync(require('path').join(ICRP116_OUT_DIR, f));
            cleared++;
        }
        return { cleared };
    } catch (e) {
        return { cleared: 0, error: e.message };
    }
}

/**
 * POST /api/icrp116/reset
 * 清空 mcnp_outputs 目录，重置任务状态。
 * 供前端页面加载时调用，确保每次从干净状态开始。
 * 任务运行中时拒绝（返回 success: false）。
 */
app.post('/api/icrp116/reset', (req, res) => {
    if (icrp116Job.running) {
        return res.json({ success: false, message: '验证任务正在运行中，无法重置' });
    }
    const result = clearIcrp116Outputs();
    icrp116Job.completed    = false;
    icrp116Job.failed       = false;
    icrp116Job.logs         = [];
    icrp116Job.doneEnergies = [];
    icrp116Job.currentCase  = null;
    icrp116Job.startTime    = null;
    console.log(`[ICRP116] reset: 已清空 ${result.cleared} 个文件`);
    res.json({ success: true, cleared: result.cleared });
});

/**
 * POST /api/icrp116/start-validation
 * 启动 MCNP5 ICRP-116 验证（后台运行，立即返回）
 * body: { energies: [0.01, 0.1, 1.0, 10.0] }  // 可选，默认全部
 */
app.post('/api/icrp116/start-validation', (req, res) => {
    if (icrp116Job.running) {
        return res.json({ success: false, message: '验证任务正在运行中，请等待完成或先取消' });
    }

    // 重置状态（不清空文件，由 Python 脚本的跳过逻辑决定是否重跑）
    icrp116Job.running        = true;
    icrp116Job.completed      = false;
    icrp116Job.failed         = false;
    icrp116Job.logs           = [];
    icrp116Job.doneEnergies   = [];
    icrp116Job.currentCase    = null;
    icrp116Job.startTime      = Date.now();
    icrp116Job.sexAvg         = false;
    icrp116Job.phase          = 'AM';
    icrp116Job.afCurrentCase  = null;
    icrp116Job.afDoneEnergies = [];

    const { energies, sexAvg } = req.body || {};
    icrp116Job.sexAvg = !!sexAvg;

    const args = [
        ICRP116_SCRIPT,
        '--inp-dir',     ICRP116_INP_DIR,
        '--out-dir',     ICRP116_OUT_DIR,
        '--backend-dir', __dirname,
        '--xsdir',       String.raw`D:\LANL\xsdir`,
        '--nps',         '10000000',
    ];
    if (Array.isArray(energies) && energies.length > 0) {
        args.push('--only', ...energies.map(String));
    }
    // AF 体模控制
    if (!sexAvg) {
        args.push('--no-run-af');
    }

    console.log('[ICRP116] 启动验证:', args.slice(1).join(' '));

    const proc = spawn(PYTHON_PATH, args, { cwd: __dirname });
    icrp116Job.pid  = proc.pid;
    icrp116Job.proc = proc;

    const pushLog = (text) => {
        const entry = { time: new Date().toLocaleTimeString('zh-CN'), text };
        icrp116Job.logs.push(entry);
        if (icrp116Job.logs.length > 500) icrp116Job.logs.shift();
        console.log('[ICRP116]', text);
    };

    proc.stdout.on('data', (data) => {
        data.toString().split('\n').filter(l => l.trim()).forEach(line => {
            pushLog(line);
            // 检测 AF 阶段开始
            if (line.includes('[AF]') && line.includes('开始 AF 体模运行')) {
                icrp116Job.phase = 'AF';
            }
            // 解析当前能量
            const mCur = line.match(/E\s*=\s*([\d.]+)\s*MeV/);
            if (mCur) {
                const e = parseFloat(mCur[1]);
                if (icrp116Job.phase === 'AF') icrp116Job.afCurrentCase = e;
                else icrp116Job.currentCase = e;
            }
            // 解析完成能量（AM/AF 汇总行）
            const mDone = line.match(/E=([\d.]+)\s*MeV\s*:\s*OK/i);
            if (mDone) {
                const e = parseFloat(mDone[1]);
                if (icrp116Job.phase === 'AF') {
                    if (!icrp116Job.afDoneEnergies.includes(e))
                        icrp116Job.afDoneEnergies.push(e);
                } else {
                    if (!icrp116Job.doneEnergies.includes(e))
                        icrp116Job.doneEnergies.push(e);
                }
            }
        });
    });

    proc.stderr.on('data', (data) => {
        data.toString().split('\n').filter(l => l.trim()).forEach(line => {
            pushLog('[ERR] ' + line);
        });
    });

    proc.on('close', (code) => {
        icrp116Job.running = false;
        icrp116Job.proc    = null;
        if (code === 0) {
            icrp116Job.completed = true;
            pushLog('✓ 全部验证任务完成！可在 icrp_validation/mcnp_outputs/ 查看结果。');
        } else {
            icrp116Job.failed = true;
            pushLog(`[错误] 进程退出码 ${code}，请检查日志`);
        }
        console.log('[ICRP116] 进程结束，code=', code);
    });

    res.json({ success: true, message: '验证任务已启动，请在日志面板查看进度' });
});

/**
 * GET /api/icrp116/status
 * 返回当前任务状态与最近 200 条日志
 */
app.get('/api/icrp116/status', (req, res) => {
    const elapsed = icrp116Job.startTime
        ? Math.floor((Date.now() - icrp116Job.startTime) / 1000)
        : 0;

    // 检查已完成的 npy 文件（AM）
    const resultFiles = [];
    try {
        const files = require('fs').readdirSync(ICRP116_OUT_DIR);
        files.filter(f => f.startsWith('fluence_') && f.endsWith('.npy'))
             .forEach(f => resultFiles.push(f));
    } catch (_) {}

    // 检查已完成的 AF npy 文件
    const afResultFiles = [];
    try {
        const files = require('fs').readdirSync(ICRP116_AF_OUT_DIR);
        files.filter(f => f.startsWith('fluence_') && f.endsWith('.npy'))
             .forEach(f => afResultFiles.push(f));
    } catch (_) {}

    res.json({
        running:        icrp116Job.running,
        completed:      icrp116Job.completed,
        failed:         icrp116Job.failed,
        currentCase:    icrp116Job.currentCase,
        doneEnergies:   icrp116Job.doneEnergies,
        elapsedSec:     elapsed,
        logs:           icrp116Job.logs.slice(-200),
        resultFiles,
        // AF 性别平均扩展字段
        sexAvg:         icrp116Job.sexAvg,
        phase:          icrp116Job.phase,
        afCurrentCase:  icrp116Job.afCurrentCase,
        afDoneEnergies: icrp116Job.afDoneEnergies,
        afResultFiles,
    });
});

/**
 * POST /api/icrp116/cancel
 * 取消正在运行的验证任务
 */
app.post('/api/icrp116/cancel', (req, res) => {
    if (!icrp116Job.running) {
        return res.json({ success: false, message: '当前没有正在运行的任务' });
    }
    try {
        if (icrp116Job.proc) icrp116Job.proc.kill('SIGTERM');
        icrp116Job.running = false;
        icrp116Job.failed  = true;
        icrp116Job.logs.push({ time: new Date().toLocaleTimeString('zh-CN'), text: '已取消' });
        res.json({ success: true, message: '任务已取消' });
    } catch (e) {
        res.status(500).json({ success: false, message: e.message });
    }
});

/**
 * POST /api/icrp116/run-step3
 * 运行 mcnp_icrp_step3_compare.py，等待完成，返回对比结果 JSON
 */
const ICRP116_STEP3_SCRIPT = path.join(__dirname, 'mcnp_icrp_step3_compare.py');
const ICRP116_MASK_PATH    = path.join(__dirname, 'icrp_validation', 'organ_mask_127x63x111.npy');
const ICRP116_ZIP_PATH     = path.join(__dirname, '..', 'P110 data V1.2', 'AM.zip');
const ICRP116_CSV_PATH     = path.join(ICRP116_OUT_DIR, 'icrp116_comparison.csv');
const ICRP116_PNG_PATH     = path.join(ICRP116_OUT_DIR, 'icrp116_comparison.png');

app.post('/api/icrp116/run-step3', (req, res) => {
    const fs = require('fs');
    const args = [
        ICRP116_STEP3_SCRIPT,
        '--out-dir', ICRP116_OUT_DIR,
        '--mask',    ICRP116_MASK_PATH,
        '--zip',     ICRP116_ZIP_PATH,
    ];
    // 自动检测 AF 输出：若有 AF npy 文件且有 AF 掩膜，则传入性别平均参数
    const hasAFNpy  = fs.existsSync(ICRP116_AF_OUT_DIR) &&
        fs.readdirSync(ICRP116_AF_OUT_DIR).some(f => f.endsWith('.npy'));
    const hasAFMask = fs.existsSync(ICRP116_AF_MASK);
    if (hasAFNpy && hasAFMask) {
        args.push('--af-out-dir', ICRP116_AF_OUT_DIR,
                  '--af-mask',    ICRP116_AF_MASK,
                  '--af-zip',     ICRP116_AF_ZIP);
        console.log('[ICRP116-Step3] 检测到 AF 输出，启用性别平均');
    }
    console.log('[ICRP116-Step3] 启动:', args.slice(1).join(' '));

    const proc = spawn(PYTHON_PATH, args, { cwd: __dirname });
    const logs = [];
    let stderr = '';

    proc.stdout.on('data', d => {
        d.toString().split('\n').filter(l => l.trim()).forEach(l => {
            logs.push(l);
            console.log('[Step3]', l);
        });
    });
    proc.stderr.on('data', d => { stderr += d.toString(); });

    proc.on('close', (code) => {
        if (code !== 0) {
            console.error('[Step3] 退出码', code, stderr.slice(0, 500));
            return res.json({ success: false, message: `Step3 退出码 ${code}：${stderr.slice(0, 200)}`, logs });
        }
        // 读取 CSV 结果（优先读取性别平均 CSV，其次标准 AM CSV）
        try {
            const sexAvgCsvPath = path.join(ICRP116_OUT_DIR, 'icrp116_comparison_sexavg.csv');
            const useSexAvg = hasAFNpy && hasAFMask && fs.existsSync(sexAvgCsvPath);
            const csvPath = useSexAvg ? sexAvgCsvPath : ICRP116_CSV_PATH;
            const csv = fs.readFileSync(csvPath, 'utf-8');
            const lines = csv.split('\n').map(l => l.trim()).filter(l => l);
            let results;
            if (useSexAvg) {
                // 8列: Energy_MeV,h_AM_pSv_cm2,h_AF_pSv_cm2,h_avg_pSv_cm2,h_ref_pSv_cm2,dev_AM_pct,dev_AF_pct,dev_avg_pct,pass
                results = lines.slice(1).map(line => {
                    const [energy, h_AM, h_AF, h_avg, h_ref, dev_AM, dev_AF, dev_avg, pass_flag] = line.split(',');
                    return {
                        energy:  parseFloat(energy),
                        h_AM:    parseFloat(h_AM),
                        h_AF:    parseFloat(h_AF),
                        h_avg:   parseFloat(h_avg),
                        h_ref:   parseFloat(h_ref),
                        dev_AM:  parseFloat(dev_AM),
                        dev_AF:  parseFloat(dev_AF),
                        dev_avg: parseFloat(dev_avg),
                        pass:    (pass_flag || '').trim(),
                    };
                }).filter(r => !isNaN(r.energy));
            } else {
                // 6列: Energy_MeV,h_calc_pSv_cm2,h_ref_pSv_cm2,deviation_pct,pass,source
                results = lines.slice(1).map(line => {
                    const [energy, h_calc, h_ref, deviation, pass_flag, source] = line.split(',');
                    return {
                        energy:    parseFloat(energy),
                        h_calc:    parseFloat(h_calc),
                        h_ref:     parseFloat(h_ref),
                        deviation: parseFloat(deviation),
                        pass:      (pass_flag || '').trim(),
                        source:    (source    || '').trim(),
                    };
                }).filter(r => !isNaN(r.energy));
            }
            res.json({ success: true, results, sexAvg: useSexAvg, logs });
        } catch (e) {
            res.json({ success: false, message: 'CSV 读取失败: ' + e.message, logs });
        }
    });

    proc.on('error', (e) => {
        res.json({ success: false, message: '启动失败: ' + e.message, logs });
    });
});

/**
 * GET /api/icrp116/chart-image
 * 返回已生成的对比图 PNG（base64）
 */
app.get('/api/icrp116/chart-image', (req, res) => {
    try {
        const fs = require('fs');
        if (!fs.existsSync(ICRP116_PNG_PATH)) {
            return res.json({ success: false, message: '图表尚未生成，请先点击「计算」按钮' });
        }
        const imageBase64 = fs.readFileSync(ICRP116_PNG_PATH).toString('base64');
        res.json({ success: true, imageBase64 });
    } catch (e) {
        res.json({ success: false, message: e.message });
    }
});

/**
 * GET /api/icrp116/check-xsdir
 * 扫描 D:\LANL\xsdir，返回可用光子截面库列表
 */
app.get('/api/icrp116/check-xsdir', (req, res) => {
    const xsdirPath = String.raw`D:\LANL\xsdir`;
    const preferred = ['.70p', '.12p', '.04p', '.24p'];
    try {
        const fs = require('fs');
        if (!fs.existsSync(xsdirPath)) {
            return res.json({
                success: false,
                message: `xsdir 文件不存在: ${xsdirPath}，请确认 MCNP5 安装路径`,
                available: [],
            });
        }
        const content = fs.readFileSync(xsdirPath, 'utf-8');
        // Use regex to match actual xsdir entry lines (ZAID.LLp at line start),
        // avoiding false-positives from comments or path strings.
        const foundDigits = new Set();
        const rx = /^\s*\d+\.(\d{2,3})p\s/mg;
        let m;
        while ((m = rx.exec(content)) !== null) foundDigits.add(m[1]);
        const available = preferred.filter(s => {
            const digits = s.replace('.', '').replace('p', ''); // '.04p' -> '04'
            return foundDigits.has(digits);
        });
        const recommended = available[0] || null;
        res.json({
            success: true,
            xsdirPath,
            available,
            recommended,
            message: available.length
                ? `检测到光子截面库: ${available.join(', ')}，推荐使用 ${recommended}`
                : 'xsdir 中未找到光子截面库条目（.70p / .12p / .04p / .24p 均未检出实际数据行）。\n'
                  + '这意味着 MCNP5 未安装光子截面数据（如 MCPLIB04）。\n'
                  + '需从 RSICC 获取并安装光子截面库，并在 xsdir 中注册后才能运行光子输运计算。',
        });
    } catch (e) {
        res.json({ success: false, message: `读取 xsdir 失败: ${e.message}`, available: [] });
    }
});

console.log('[ICRP116] API端点已加载:');
console.log('  - POST /api/icrp116/reset');
console.log('  - POST /api/icrp116/start-validation');
console.log('  - GET  /api/icrp116/status');
console.log('  - POST /api/icrp116/cancel');
console.log('  - POST /api/icrp116/run-step3');
console.log('  - GET  /api/icrp116/chart-image');
console.log('  - GET  /api/icrp116/check-xsdir');

app.listen(PORT, () => {
    log(`服务器已启动: http://localhost:${PORT}`);
});