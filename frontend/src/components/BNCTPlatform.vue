<template>
  <div class="bnct-platform">
    <!-- 顶部导航栏 -->
    <header class="platform-header">
      <div class="logo-section">
        <h1>🔬 智慧BNCT治疗规划平台</h1>
        <span class="version">v2.0</span>
      </div>
      <nav class="nav-tabs">
        <button 
          v-for="tab in tabs" 
          :key="tab.id"
          :class="['nav-tab', { active: activeTab === tab.id }]"
          @click="activeTab = tab.id"
        >
          {{ tab.icon }} {{ tab.name }}
        </button>
      </nav>
    </header>

    <!-- 主内容区域 -->
    <main class="main-content">
      <!-- Tab 1: CT影像处理 -->
      <div v-show="activeTab === 'imaging'" class="tab-content">
        <div class="workspace">
          <!-- 左侧控制面板 -->
          <aside class="control-panel">
            <div class="panel-section">
              <h3>📁 文件管理</h3>
              <button @click="$refs.fileInput.click()" class="btn btn-primary">
                <span class="icon">📤</span>
                上传NIfTI文件 (.nii.gz)
              </button>
              <input 
                ref="fileInput" 
                type="file" 
                @change="handleNiiUpload" 
                accept=".nii.gz" 
                style="display: none"
              />
              
              <div v-if="uploadedFile" class="file-info">
                <div class="info-item">
                  <span class="label">文件名:</span>
                  <span class="value">{{ uploadedFile.name }}</span>
                </div>
                <div class="info-item">
                  <span class="label">大小:</span>
                  <span class="value">{{ formatFileSize(uploadedFile.size) }}</span>
                </div>
                <div class="info-item">
                  <span class="label">状态:</span>
                  <span class="value status-success">✓ 已加载</span>
                </div>
              </div>
            </div>

            <div class="panel-section">
              <h3>🎯 视图控制</h3>
              <div class="view-controls">
                <div v-for="view in ['axial', 'coronal', 'sagittal']" :key="view" class="control-item">
                  <label>{{ viewNames[view] }}</label>
                  <input 
                    v-model.number="sliceIndices[view]"
                    type="range"
                    :min="0"
                    :max="Math.max(0, (slices[view] && slices[view].length ? slices[view].length : 1) - 1)"
                    class="slider"
                  />
                  <span class="slice-number">
                    {{ sliceIndices[view] + 1 }} / {{ slices[view] && slices[view].length ? slices[view].length : 0 }}
                  </span>
                </div>
              </div>
            </div>


          </aside>

          <!-- 右侧影像显示区 -->
          <section class="image-viewer">
            <div class="viewer-grid">
              <div 
                v-for="view in ['axial', 'coronal', 'sagittal']" 
                :key="view" 
                class="viewer-panel"
              >
                <div class="panel-header">
                  <h4>{{ viewNames[view] }}切面</h4>
                  <div class="panel-actions">
                    <button @click="toggleFullscreen(view)" class="btn-icon" title="全屏">⛶</button>
                  </div>
                </div>
                <div class="image-container">
                  <img 
                    v-if="slices[view] && slices[view][sliceIndices[view]]"
                    :src="getImageUrl(slices[view][sliceIndices[view]])"
                    :alt="`${viewNames[view]}切片`"
                    class="medical-image"
                    @error="handleImageError"
                  />
                  <!-- 剂量叠加层 -->
                  <img 
                    v-if="slices['dose' + capitalize(view)] && slices['dose' + capitalize(view)][sliceIndices[view]]"
                    :src="getImageUrl(slices['dose' + capitalize(view)][sliceIndices[view]])"
                    class="dose-overlay"
                    :style="{ opacity: doseOpacity / 100 }"
                  />
                  <div v-if="!slices[view] || slices[view].length === 0" class="placeholder">
                    <p>📷</p>
                    <p>等待加载影像数据...</p>
                  </div>
                  <!-- 十字线 -->
                  <div v-if="showCrosshair" class="crosshair">
                    <div class="crosshair-h"></div>
                    <div class="crosshair-v"></div>
                  </div>
                </div>
                <div class="image-info">
                  <span>切片: {{ sliceIndices[view] + 1 }}/{{ slices[view] && slices[view].length ? slices[view].length : 0 }}</span>
                  <span v-if="imageMetadata[view]">{{ imageMetadata[view].spacing }} mm</span>
                </div>
              </div>
            </div>

            <!-- 剂量透明度控制（已禁用 - PNG图像无法动态调整） -->
            <!--
            <div v-if="hasDoseData" class="dose-control-bar">
              <label>剂量叠加透明度:</label>
              <input v-model.number="doseOpacity" type="range" min="0" max="100" class="slider" />
              <span>{{ doseOpacity }}%</span>
            </div>
            -->
          </section>
        </div>
      </div>

      <!-- Tab 2: MCNP计算 -->
      <div v-show="activeTab === 'mcnp'" class="tab-content">
        <div class="mcnp-workspace">

          <!-- 患者参数面板 (用于体模选择和缩放) -->
          <div class="patient-params-panel" style="margin-bottom:16px; padding:16px; background:#f0f7ff; border-radius:8px; border:1px solid #d0e3f7;">
            <h3 style="margin:0 0 12px 0;">🧑‍⚕️ 患者参数（体模构建用）</h3>
            <div style="display:flex; gap:16px; flex-wrap:wrap;">
              <div class="control-item">
                <label>性别</label>
                <select v-model="phantomGender" style="padding:6px 10px; border-radius:4px; border:1px solid #ccc;">
                  <option value="male">男性 (AM体模)</option>
                  <option value="female">女性 (AF体模)</option>
                </select>
              </div>
              <div class="control-item">
                <label>肿瘤区域</label>
                <select v-model="phantomTumorRegion" style="padding:6px 10px; border-radius:4px; border:1px solid #ccc;">
                  <option value="">自动识别</option>
                  <option value="brain">脑部 (Brain)</option>
                  <option value="nasopharynx">鼻咽 (Nasopharynx)</option>
                  <option value="chest">胸部 (Chest)</option>
                  <option value="abdomen">腹部 (Abdomen)</option>
                  <option value="liver">肝脏 (Liver)</option>
                  <option value="pelvis">骨盆 (Pelvis)</option>
                </select>
              </div>
            </div>
          </div>

          <div class="workflow-steps">
            <div 
              v-for="(step, index) in mcnpSteps" 
              :key="index"
              :class="['workflow-step', { 
                completed: step.status === 'completed',
                active: step.status === 'active',
                error: step.status === 'error'
              }]"
            >
              <div class="step-number">{{ index + 1 }}</div>
              <div class="step-content">
                <h4>{{ step.title }}</h4>
                <p>{{ step.description }}</p>
                <button 
                  v-if="step.action"
                  @click="step.action"
                  :disabled="step.disabled || loading"
                  class="btn btn-primary"
                >
                  {{ loading && currentStep === index ? '处理中...' : step.buttonText }}
                </button>
                <div v-if="step.status === 'active' && loading" class="progress-bar">
                  <div class="progress-fill" :style="{ width: progress + '%' }"></div>
                </div>
                <div v-if="step.result" class="step-result">
                  {{ step.result }}
                </div>
              </div>
              <div class="step-status">
                <span v-if="step.status === 'completed'" class="status-icon success">✓</span>
                <span v-else-if="step.status === 'error'" class="status-icon error">✗</span>
                <span v-else-if="step.status === 'active'" class="status-icon active">⟳</span>
              </div>
            </div>
          </div>

          <!-- 日志输出 -->
          <div class="log-panel">
            <div class="log-header">
              <h4>📋 计算日志</h4>
              <button @click="clearLogs" class="btn btn-secondary">清空</button>
            </div>
            <div class="log-content" ref="logContent">
              <div v-for="(log, index) in logs" :key="index" :class="['log-entry', log.type]">
                <span class="log-time">{{ log.time }}</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
              <div v-if="logs.length === 0" class="log-empty">
                暂无日志记录
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ========================================= -->
<!-- 改进的剂量分析Tab - 支持三视图多切片浏览 -->
<!-- ========================================= -->

<!-- Tab 3: 剂量分析 -->
<div v-show="activeTab === 'dose'" class="tab-content">
  <div class="dose-workspace">
    <!-- 左侧控制面板 -->
    <aside class="dose-control-panel">
      <!-- 剂量数据上传 -->
      <div class="panel-section">
        <h3>📊 剂量数据上传</h3>
        <div class="upload-area" @drop.prevent="handleDoseDrop" @dragover.prevent>
          <button @click="$refs.doseInput.click()" class="btn btn-primary">
            <span class="icon">📁</span>
            选择剂量文件 (.npy)
          </button>
          <input 
            ref="doseInput" 
            type="file" 
            @change="handleDoseUpload" 
            accept=".npy" 
            multiple 
            style="display: none"
          />
          <p class="hint">或拖拽文件到此处</p>
          <div v-if="doseFiles.length > 0" class="file-list">
            <div v-for="(file, index) in doseFiles" :key="index" class="file-item">
              <span>{{ file.name }}</span>
              <button @click="removeDoseFile(index)" class="btn-remove">×</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 剂量切片控制 -->
      <div v-if="hasDoseData" class="panel-section">
        <h3>🎯 剂量切片控制</h3>
        <div class="view-controls">
          <div v-for="view in ['axial', 'coronal', 'sagittal']" :key="view" class="control-item">
            <label>{{ viewNames[view] }}</label>
            <input 
              v-model.number="doseSliceIndices[view]"
              type="range"
              :min="0"
              :max="Math.max(0, (slices['dose' + capitalize(view)] && slices['dose' + capitalize(view)].length ? slices['dose' + capitalize(view)].length : 1) - 1)"
              class="slider"
            />
            <span class="slice-number">
              {{ doseSliceIndices[view] + 1 }} / {{ slices['dose' + capitalize(view)] && slices['dose' + capitalize(view)].length ? slices['dose' + capitalize(view)].length : 0 }}
            </span>
          </div>
        </div>
      </div>

      <!-- 显示设置 -->
      <div v-if="hasDoseData" class="panel-section">
        <h3>🎨 显示设置</h3>
        <div class="control-info">
          <p style="color: #666; font-size: 12px; padding: 8px; background: #f0f4ff; border-radius: 4px;">
            💡 显示的是MCNP计算后全身体模上的剂量分布。<br>
            体模外部区域（空气）无剂量显示。<br>
            如需调整显示参数，请重新生成剂量分布图。
          </p>
        </div>
      </div>

      <!-- 剂量统计信息 -->
      <div v-if="hasDoseData && doseStats" class="panel-section">
        <h3>📈 剂量统计</h3>
        <div class="stats-grid">
          <div class="stat-item">
            <span class="stat-label">最大剂量</span>
            <span class="stat-value">{{ doseStats.max.toFixed(2) }} Gy</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">平均剂量</span>
            <span class="stat-value">{{ doseStats.mean.toFixed(2) }} Gy</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">覆盖体积</span>
            <span class="stat-value">{{ doseStats.coverage.toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <!-- 导出功能 -->
      <div v-if="hasDoseData" class="panel-section">
        <h3>💾 导出</h3>
      </div>
    </aside>

    <!-- 右侧剂量显示区域 -->
    <section class="dose-viewer">
      <!-- 新布局：轴向较小，冠状和矢状为高长方形 -->
      <div class="dose-viewer-grid">
        
        <!-- 轴向：横扁形 -->
        <div class="dose-panel dose-panel--axial">
          <div class="panel-header">
            <h4>{{ viewNames['axial'] }}剂量分布</h4>
            <div class="panel-actions">
              <button @click="toggleDoseFullscreen('axial')" class="btn-icon" title="全屏">⛶</button>
            </div>
          </div>
          <div class="dose-image-wrapper dose-image-wrapper--axial">
            <img
              v-if="slices.doseAxial && slices.doseAxial[doseSliceIndices.axial]"
              :src="getImageUrl(slices.doseAxial[doseSliceIndices.axial])"
              alt="轴位剂量分布"
              class="dose-image"
            />
            <div v-else class="placeholder">
              <p>📈</p><p>等待剂量数据...</p>
              <p class="hint-small">完成MCNP计算后自动加载</p>
            </div>
            <div v-if="slices.doseAxial && slices.doseAxial[doseSliceIndices.axial]" class="slice-info-overlay">
              <span>轴位 - 切片 {{ doseSliceIndices.axial + 1 }}/{{ slices.doseAxial.length }}</span>
            </div>
          </div>
          <div v-if="slices.doseAxial && slices.doseAxial.length > 0" class="slice-nav-buttons">
            <button @click="previousDoseSlice('axial')" :disabled="doseSliceIndices.axial === 0" class="nav-btn">◀ 上一张</button>
            <button @click="nextDoseSlice('axial')" :disabled="doseSliceIndices.axial >= slices.doseAxial.length - 1" class="nav-btn">下一张 ▶</button>
          </div>
        </div>

        <!-- 冠状：竖长方形，较大 -->
        <div class="dose-panel dose-panel--coronal">
          <div class="panel-header">
            <h4>{{ viewNames['coronal'] }}剂量分布</h4>
            <div class="panel-actions">
              <button @click="toggleDoseFullscreen('coronal')" class="btn-icon" title="全屏">⛶</button>
            </div>
          </div>
          <div class="dose-image-wrapper dose-image-wrapper--coronal">
            <img
              v-if="slices.doseCoronal && slices.doseCoronal[doseSliceIndices.coronal]"
              :src="getImageUrl(slices.doseCoronal[doseSliceIndices.coronal])"
              alt="冠状剂量分布"
              class="dose-image"
            />
            <div v-else class="placeholder">
              <p>📈</p><p>等待剂量数据...</p>
              <p class="hint-small">完成MCNP计算后自动加载</p>
            </div>
            <div v-if="slices.doseCoronal && slices.doseCoronal[doseSliceIndices.coronal]" class="slice-info-overlay">
              <span>冠状 - 切片 {{ doseSliceIndices.coronal + 1 }}/{{ slices.doseCoronal.length }}</span>
            </div>
          </div>
          <div v-if="slices.doseCoronal && slices.doseCoronal.length > 0" class="slice-nav-buttons">
            <button @click="previousDoseSlice('coronal')" :disabled="doseSliceIndices.coronal === 0" class="nav-btn">◀ 上一张</button>
            <button @click="nextDoseSlice('coronal')" :disabled="doseSliceIndices.coronal >= slices.doseCoronal.length - 1" class="nav-btn">下一张 ▶</button>
          </div>
        </div>

        <!-- 矢状：竖长方形，较大 -->
        <div class="dose-panel dose-panel--sagittal">
          <div class="panel-header">
            <h4>{{ viewNames['sagittal'] }}剂量分布</h4>
            <div class="panel-actions">
              <button @click="toggleDoseFullscreen('sagittal')" class="btn-icon" title="全屏">⛶</button>
            </div>
          </div>
          <div class="dose-image-wrapper dose-image-wrapper--sagittal">
            <img
              v-if="slices.doseSagittal && slices.doseSagittal[doseSliceIndices.sagittal]"
              :src="getImageUrl(slices.doseSagittal[doseSliceIndices.sagittal])"
              alt="矢状剂量分布"
              class="dose-image"
            />
            <div v-else class="placeholder">
              <p>📈</p><p>等待剂量数据...</p>
              <p class="hint-small">完成MCNP计算后自动加载</p>
            </div>
            <div v-if="slices.doseSagittal && slices.doseSagittal[doseSliceIndices.sagittal]" class="slice-info-overlay">
              <span>矢状 - 切片 {{ doseSliceIndices.sagittal + 1 }}/{{ slices.doseSagittal.length }}</span>
            </div>
          </div>
          <div v-if="slices.doseSagittal && slices.doseSagittal.length > 0" class="slice-nav-buttons">
            <button @click="previousDoseSlice('sagittal')" :disabled="doseSliceIndices.sagittal === 0" class="nav-btn">◀ 上一张</button>
            <button @click="nextDoseSlice('sagittal')" :disabled="doseSliceIndices.sagittal >= slices.doseSagittal.length - 1" class="nav-btn">下一张 ▶</button>
          </div>
        </div>
      </div>

      <!-- 色标 -->
      <div v-if="hasDoseData" class="colorbar-section">
        <div class="colorbar">
          <div :class="['colorbar-gradient', doseColormap]"></div>
          <div class="colorbar-labels">
            <span>0 Gy</span>
            <span>低剂量</span>
            <span>中剂量</span>
            <span>高剂量</span>
            <span v-if="doseStats">{{ doseStats.max.toFixed(1) }} Gy</span>
            <span v-else>最大剂量</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</div>

<!-- ========================================= -->
<!-- 对应的methods需要添加的内容 -->
<!-- ========================================= -->

<!-- ========================================= -->
<!-- 对应的CSS样式需要添加的内容 -->
<!-- ========================================= -->


      <!-- Tab 4: DVH分析 -->
      <div v-show="activeTab === 'dvh'" class="tab-content">
        <div class="dvh-workspace">
          <div class="dvh-controls">
            <h3>🏥 器官掩膜上传</h3>
            <button @click="$refs.organInput.click()" class="btn btn-primary">
              <span class="icon">📤</span>
              上传器官掩膜 (.nii.gz)
            </button>
            <input 
              ref="organInput" 
              type="file" 
              @change="handleOrganUpload" 
              accept=".nii.gz" 
              multiple 
              style="display: none"
            />
            
            <div v-if="organFiles.length > 0" class="organ-list">
              <h4>已上传器官:</h4>
              <div v-for="(organ, index) in organFiles" :key="index" class="organ-item">
                <span class="organ-name">{{ organ.name }}</span>
                <button @click="removeOrgan(index)" class="btn-remove">×</button>
              </div>
            </div>

            <button 
              @click="generateDVH" 
              :disabled="!canGenerateDVH || loading"
              class="btn btn-success btn-large"
            >
              {{ loading ? '生成中...' : '生成DVH图表' }}
            </button>
          </div>

          <div class="dvh-display">
            <div v-if="dvhImage" class="dvh-chart">
              <h3>剂量体积直方图 (DVH)</h3>
              <img :src="dvhImage" alt="DVH图表" class="dvh-img" />
              <button @click="exportDVH" class="btn btn-secondary">导出DVH数据</button>
            </div>
            <div v-else class="placeholder-large">
              <p>📊</p>
              <p>DVH图表将在此显示</p>
              <p class="hint">请先上传器官掩膜并生成DVH</p>
            </div>

            <!-- DVH统计信息 -->
            <div v-if="dvhStats" class="dvh-stats">
              <h4>统计信息</h4>
              <table class="stats-table">
                <thead>
                  <tr>
                    <th>器官</th>
                    <th>平均剂量</th>
                    <th>最大剂量</th>
                    <th>D95</th>
                    <th>V20</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="stat in dvhStats" :key="stat.organ">
                    <td>{{ stat.organ }}</td>
                    <td>{{ stat.meanDose }} Gy</td>
                    <td>{{ stat.maxDose }} Gy</td>
                    <td>{{ stat.d95 }} Gy</td>
                    <td>{{ stat.v20 }} %</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 5: 全身风险评估 -->
      <div v-show="activeTab === 'risk'" class="tab-content">
        <div class="risk-workspace">
          <div class="risk-assessment-panel">
            <h3>🧬 全身风险评估</h3>
            
            <div class="assessment-steps">
              <div class="step">
                <h4>1. 患者CT数据</h4>
                <button @click="$refs.patientCtInput.click()" class="btn btn-primary">
                  上传患者CT
                </button>
                <input 
                  ref="patientCtInput" 
                  type="file" 
                  @change="handlePatientCtUpload" 
                  accept=".nii.gz" 
                  style="display: none"
                />
                <div v-if="patientCtFile" class="file-info">
                  ✓ {{ patientCtFile.name }}
                </div>
              </div>

              <div class="step">
                <h4>2. 评估参数</h4>
                <div class="param-group">
                  <label>
                    <span>年龄:</span>
                    <input v-model.number="riskParams.age" type="number" min="0" max="120" />
                  </label>
                  <label>
                    <span>性别:</span>
                    <select v-model="riskParams.gender">
                      <option value="male">男</option>
                      <option value="female">女</option>
                    </select>
                  </label>
                  <label>
                    <span>辐照时间 (分钟):</span>
                    <input v-model.number="riskParams.exposureTime" type="number" min="1" max="120" />
                  </label>
                </div>
              </div>

              <div class="step">
                <h4>3. 运行评估</h4>
                <button 
                  @click="runRiskAssessment" 
                  :disabled="!canRunRiskAssessment || loading"
                  class="btn btn-success btn-large"
                >
                  {{ loading ? '评估中...' : '开始风险评估' }}
                </button>
              </div>
            </div>

            <!-- 评估结果 -->
            <div v-if="riskResults" class="risk-results">
              <h3>评估结果</h3>
              
              <div class="result-card">
                <h4>总体风险评分</h4>
                <div class="risk-score" :class="getRiskLevel(riskResults.totalRisk)">
                  {{ riskResults.totalRisk.toFixed(2) }}
                </div>
                <p class="risk-description">{{ getRiskDescription(riskResults.totalRisk) }}</p>
              </div>

              <div class="organ-risks">
                <h4>器官风险分布</h4>
                <div class="risk-chart">
                  <!-- 这里可以集成图表库显示器官风险 -->
                  <div v-for="organ in riskResults.organs" :key="organ.name" class="organ-risk-bar">
                    <span class="organ-label">{{ organ.name }}</span>
                    <div class="risk-bar-container">
                      <div 
                        class="risk-bar-fill" 
                        :style="{ width: (organ.risk / riskResults.maxRisk * 100) + '%' }"
                        :class="getRiskLevel(organ.risk)"
                      ></div>
                    </div>
                    <span class="risk-value">{{ organ.risk.toFixed(3) }}</span>
                  </div>
                </div>
              </div>

              <button @click="exportRiskReport" class="btn btn-primary">
                导出评估报告
              </button>
            </div>
          </div>

          <!-- 可视化 -->
          <div class="risk-visualization">
            <h4>风险分布可视化</h4>
            <div class="viz-container">
              <div v-if="riskVisualization" class="risk-3d-view">
                <img :src="riskVisualization" alt="风险分布" />
              </div>
              <div v-else class="placeholder-large">
                <p>🎯</p>
                <p>风险分布可视化将在此显示</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- 消息提示 -->
    <transition name="fade">
      <div v-if="message" :class="['message-toast', messageType]">
        <span class="toast-icon">
          {{ messageType === 'success' ? '✓' : messageType === 'error' ? '✗' : 'ℹ' }}
        </span>
        <span class="toast-message">{{ message }}</span>
        <button @click="message = ''" class="toast-close">×</button>
      </div>
    </transition>

    <!-- 加载遮罩 -->
    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <p>{{ loadingMessage }}</p>
    </div>
  </div>
</template>

<script>
import axios from 'axios';

const API_BASE = 'http://localhost:3000';

export default {
  name: 'BNCTPlatform',
  data() {
    return {
      // Tab管理
      activeTab: 'imaging',
      tabs: [
        { id: 'imaging', name: 'CT影像', icon: '🖼️' },
        { id: 'mcnp', name: 'MCNP计算', icon: '⚛️' },
        { id: 'dose', name: '剂量分析', icon: '📊' },
        { id: 'dvh', name: 'DVH分析', icon: '📈' },
        { id: 'risk', name: '风险评估', icon: '🏥' }
      ],

      // 影像数据
      slices: {
        axial: [],
        coronal: [],
        sagittal: [],
        doseAxial: [],
        doseCoronal: [],
        doseSagittal: []
      },
      sliceIndices: { axial: 0, coronal: 0, sagittal: 0 },
      viewNames: {
        axial: '轴向',
        coronal: '冠状',
        sagittal: '矢状'
      },
      imageMetadata: {},

      // 文件管理
      uploadedFile: null,
      niiPath: '',
      npyPath: '',
      folderName: '',

      // 剂量数据
      doseFiles: [],
      doseOpacity: 70,
      hasDoseData: false,

      // DVH
      organFiles: [],
      dvhImage: '',
      dvhStats: null,

      // 风险评估
      patientCtFile: null,
      riskParams: {
        age: 50,
        gender: 'male',
        exposureTime: 30
      },
      riskResults: null,
      riskVisualization: '',

      // MCNP工作流
      mcnpSteps: [
        {
          title: '构建全身多材料体模',
          description: '缩放ICRP体模 → 融合CT(含过渡带) → 生成多材料体素lattice MCNP输入',
          buttonText: '构建体模',
          action: null,
          status: 'pending',
          disabled: false,
          result: ''
        },
        {
          title: '运行MCNP全身计算',
          description: '在多材料体素几何中执行蒙特卡洛中子输运(耗时较长)',
          buttonText: '开始计算',
          action: null,
          status: 'pending',
          disabled: true,
          result: ''
        },
        {
          title: '生成全身剂量分布图',
          description: '从MCNP全身meshtal提取剂量数据，生成三视图可视化',
          buttonText: '生成剂量图',
          action: null,
          status: 'pending',
          disabled: true,
          result: ''
        }
      ],
      currentStep: -1,
      logs: [],

      // UI状态
      message: '',
      messageType: 'info',
      loading: false,
      loadingMessage: '',
      progress: 0,
      showCrosshair: true,

      // ========== 新增：剂量相关数据 ==========
    
      // 剂量切片独立索引（不使用CT的sliceIndices）
      doseSliceIndices: { axial: 0, coronal: 0, sagittal: 0 },
      
      // 剂量显示设置
      doseThreshold: 5,        // 显示阈值（百分比）
      doseColormap: 'jet',     // 色图方案 (与后端jet色图一致)
      
      // 剂量统计信息
      doseStats: null,         // { max, mean, coverage }

      // 体模构建参数
      phantomGender: 'male',
      phantomTumorRegion: '',   // '' = 自动识别
    };
  },

  computed: {
    canGenerateDVH() {
      return this.organFiles.length > 0 && this.hasDoseData;
    },
    canRunRiskAssessment() {
      return this.patientCtFile !== null;
    }
  },

  mounted() {
    // 绑定MCNP步骤的action
    this.mcnpSteps[0].action = this.buildWholeBodyPhantom;
    this.mcnpSteps[1].action = this.runMcnpCalculation;
    this.mcnpSteps[2].action = this.generateWholeBodyDoseMap;
  },

  methods: {
    // ========== 工具方法 ==========
    getImageUrl(path) {
      return path ? `${API_BASE}${path}?t=${Date.now()}` : '';
    },

    capitalize(str) {
      return str.charAt(0).toUpperCase() + str.slice(1);
    },

    formatFileSize(bytes) {
      if (bytes === 0) return '0 Bytes';
      const k = 1024;
      const sizes = ['Bytes', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },

    showMessage(msg, type = 'info') {
      this.message = msg;
      this.messageType = type;
      setTimeout(() => { this.message = ''; }, 5000);
    },

    addLog(message, type = 'info') {
      const time = new Date().toLocaleTimeString();
      this.logs.push({ time, message, type });
      this.$nextTick(() => {
        const logContent = this.$refs.logContent;
        if (logContent) {
          logContent.scrollTop = logContent.scrollHeight;
        }
      });
    },

    clearLogs() {
      this.logs = [];
    },

    handleImageError(e) {
      console.error('Image load error:', e.target.src);
      this.showMessage('图像加载失败', 'error');
    },

    // ========== CT影像处理 ==========
    async handleNiiUpload(e) {
      const file = e.target.files[0];
      if (!file) return;

      this.loading = true;
      this.loadingMessage = '上传并处理NIfTI文件...';
      this.uploadedFile = file;

      const formData = new FormData();
      formData.append('niiFile', file);

      try {
        const response = await axios.post(`${API_BASE}/upload-nii`, formData, {
          onUploadProgress: (progressEvent) => {
            if (progressEvent.total) {
              this.progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            }
          }
        });

        this.slices.axial = response.data.axial || [];
        this.slices.coronal = response.data.coronal || [];
        this.slices.sagittal = response.data.sagittal || [];
        this.niiPath = response.data.niiPath;
        this.npyPath = response.data.npyPath;
        this.folderName = response.data.folderName;
        this.sliceIndices = { axial: 0, coronal: 0, sagittal: 0 };

        // 启用第一个MCNP步骤
        this.mcnpSteps[0].disabled = false;

        this.showMessage('CT影像加载成功!', 'success');
      } catch (error) {
        console.error('Upload error:', error);
        this.showMessage('上传失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.loading = false;
        this.progress = 0;
      }
    },

    // eslint-disable-next-line no-unused-vars
    exportSlice(view) {
      const imageUrl = this.slices[view][this.sliceIndices[view]];
      if (!imageUrl) {
        return;
      }
      
      const link = document.createElement('a');
      link.href = this.getImageUrl(imageUrl);
      link.download = `${view}_slice_${this.sliceIndices[view]}.png`;
      link.click();
    },

    toggleFullscreen(_view) {
      // 实现全屏功能
      this.showMessage('全屏功能开发中...', 'info');
    },

    // ========== MCNP计算 ==========
    async buildWholeBodyPhantom() {
      if (!this.niiPath) {
        this.showMessage('请先上传CT影像', 'error');
        return;
      }

      this.loading = true;
      this.currentStep = 0;
      this.mcnpSteps[0].status = 'active';
      this.loadingMessage = '构建全身体模...';
      this.addLog('开始构建全身三维体模...');

      try {
        const response = await axios.post(`${API_BASE}/build-wholebody-phantom`, {
          niiPath: this.niiPath,
          gender: this.phantomGender,
          tumorRegion: this.phantomTumorRegion
        });

        this.mcnpSteps[0].status = 'completed';
        this.mcnpSteps[0].result = `体模构建完成: ${response.data.message || '成功'}`;
        this.mcnpSteps[1].disabled = false;
        
        this.addLog('全身体模构建成功', 'success');
        this.showMessage('全身体模构建成功,可以开始MCNP计算', 'success');
      } catch (error) {
        this.mcnpSteps[0].status = 'error';
        this.mcnpSteps[0].result = '构建失败';
        this.addLog('全身体模构建失败: ' + error.message, 'error');
        this.showMessage('构建失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.loading = false;
        this.currentStep = -1;
      }
    },

    async runMcnpCalculation() {
      this.loading = true;
      this.currentStep = 1;
      this.mcnpSteps[1].status = 'active';
      this.loadingMessage = 'MCNP计算中,请耐心等待...';
      this.addLog('开始MCNP蒙特卡洛模拟...');

      // 模拟进度更新
      const progressInterval = setInterval(() => {
        if (this.progress < 90) {
          this.progress += Math.random() * 5;
        }
      }, 1000);

      try {
        const response = await axios.post(`${API_BASE}/run-mcnp-computation`);

        clearInterval(progressInterval);
        this.progress = 100;

        this.mcnpSteps[1].status = 'completed';
        this.mcnpSteps[1].result = response.data.message || '计算完成';
        this.mcnpSteps[2].disabled = false;

        this.addLog('MCNP计算完成', 'success');
        this.showMessage('MCNP计算完成', 'success');
      } catch (error) {
        clearInterval(progressInterval);
        this.mcnpSteps[1].status = 'error';
        this.mcnpSteps[1].result = '计算失败';
        this.addLog('MCNP计算失败: ' + error.message, 'error');
        this.showMessage('计算失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.loading = false;
        this.currentStep = -1;
        this.progress = 0;
      }
    },

    async generateWholeBodyDoseMap() {
      this.loading = true;
      this.currentStep = 2;
      this.mcnpSteps[2].status = 'active';
      this.loadingMessage = '生成全身剂量分布图...';
      this.addLog('开始生成全身剂量可视化...');

      try {
        // 调用后端API生成剂量分布图
        // 后端会自动查找dose.npy和CT.nii文件
        const response = await axios.post(`${API_BASE}/generate-wholebody-dose-map`, {
          axialImagePath: this.slices.axial[0] || ''  // 传递CT切片路径作为参考
        });

        if (response.data.success) {
          // 更新剂量切片数据
          this.slices.doseAxial = response.data.doseAxial || [];
          this.slices.doseCoronal = response.data.doseCoronal || [];
          this.slices.doseSagittal = response.data.doseSagittal || [];
          this.hasDoseData = true;

          this.mcnpSteps[2].status = 'completed';
          this.mcnpSteps[2].result = `已生成${response.data.totalSlices || 0}张剂量切片`;

          this.addLog(`全身剂量分布图生成成功 (${response.data.totalSlices}张切片)`, 'success');
          this.showMessage('全身剂量分布图生成成功，可在"剂量分布图"标签页查看', 'success');

          // 自动切换到剂量分布图标签页
          setTimeout(() => {
            this.activeTab = 'dose';
          }, 1000);
        } else {
          throw new Error(response.data.message || '生成失败');
        }
      } catch (error) {
        this.mcnpSteps[2].status = 'error';
        this.mcnpSteps[2].result = '生成失败';
        
        const errorMsg = error.response?.data?.message || error.message;
        const troubleshooting = error.response?.data?.troubleshooting;
        
        this.addLog('剂量分布图生成失败: ' + errorMsg, 'error');
        
        let fullMessage = '生成失败: ' + errorMsg;
        if (troubleshooting) {
          fullMessage += '\n\n排查建议:\n';
          Object.entries(troubleshooting).forEach(([key, value]) => {
            fullMessage += `• ${key}: ${value}\n`;
          });
        }
        
        this.showMessage(fullMessage, 'error');
      } finally {
        this.loading = false;
        this.currentStep = -1;
      }
    },

    // ========== 剂量分析 ==========
    async handleDoseUpload(e) {
      const files = Array.from(e.target.files);
      if (files.length === 0) return;

      this.loading = true;
      this.loadingMessage = '上传剂量文件...';

      const formData = new FormData();
      files.forEach(file => {
        formData.append('doseFile', file);
      });

      try {
        const response = await axios.post(`${API_BASE}/process-npy`, formData);
        
        if (response.data.success) {
          this.doseFiles = files;
          this.slices.doseAxial = response.data.doseImages?.axial || [];
          this.slices.doseCoronal = response.data.doseImages?.coronal || [];
          this.slices.doseSagittal = response.data.doseImages?.sagittal || [];
          this.hasDoseData = true;

          const totalImages = response.data.totalImages || 0;
          this.showMessage(`剂量文件上传成功，已生成${totalImages}张剂量图像`, 'success');
          this.addLog(`剂量文件处理完成 (${totalImages}张图像)`, 'success');
        } else {
          throw new Error(response.data.message || '处理失败');
        }
      } catch (error) {
        const errorMsg = error.response?.data?.message || error.message;
        const solution = error.response?.data?.solution;
        
        let fullMessage = '上传失败: ' + errorMsg;
        if (solution) {
          fullMessage += '\n\n解决方案: ' + solution;
        }
        
        this.showMessage(fullMessage, 'error');
        this.addLog('剂量文件处理失败: ' + errorMsg, 'error');
      } finally {
        this.loading = false;
      }
    },

    handleDoseDrop(e) {
      const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.npy'));
      if (files.length > 0) {
        this.$refs.doseInput.files = files;
        this.handleDoseUpload({ target: { files } });
      }
    },
    
    previousDoseSlice(view) {
      if (this.doseSliceIndices[view] > 0) {
        this.doseSliceIndices[view]--;
      }
    },

    nextDoseSlice(view) {
      const doseKey = 'dose' + this.capitalize(view);
      const maxIndex = (this.slices[doseKey] || []).length - 1;
      if (this.doseSliceIndices[view] < maxIndex) {
        this.doseSliceIndices[view]++;
      }
    },

    toggleDoseFullscreen(_view) {
      this.showMessage('全屏功能开发中...', 'info');
      // TODO: 实现全屏显示
    },

    removeDoseFile(index) {
      this.doseFiles.splice(index, 1);
    },

    // ========== DVH分析 ==========
    async handleOrganUpload(e) {
      const files = Array.from(e.target.files);
      this.organFiles = files;
      this.showMessage(`已选择 ${files.length} 个器官掩膜文件`, 'success');
    },

    removeOrgan(index) {
      this.organFiles.splice(index, 1);
    },

    async generateDVH() {
      if (!this.canGenerateDVH) {
        this.showMessage('请先上传器官掩膜和剂量数据', 'error');
        return;
      }

      this.loading = true;
      this.loadingMessage = '生成DVH图表...';

      const formData = new FormData();
      this.organFiles.forEach(file => {
        formData.append('organMasks', file);
      });

      try {
        const response = await axios.post(`${API_BASE}/generate-dvh`, formData);
        
        this.dvhImage = response.data.dvhImagePath 
          ? `${API_BASE}${response.data.dvhImagePath}?t=${Date.now()}` 
          : '';
        this.dvhStats = response.data.stats || null;

        this.showMessage('DVH图表生成成功', 'success');
      } catch (error) {
        this.showMessage('生成失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.loading = false;
      }
    },

    exportDVH() {
      // 导出DVH数据
      this.showMessage('DVH数据导出功能开发中...', 'info');
    },

    // ========== 风险评估 ==========
    async handlePatientCtUpload(e) {
      const file = e.target.files[0];
      if (!file) return;
      
      this.patientCtFile = file;
      this.showMessage('患者CT文件已选择', 'success');
    },

    async runRiskAssessment() {
      if (!this.canRunRiskAssessment) {
        this.showMessage('请先上传患者CT数据', 'error');
        return;
      }

      this.loading = true;
      this.loadingMessage = '运行全身风险评估...';

      const formData = new FormData();
      formData.append('ctFile', this.patientCtFile);
      formData.append('age', this.riskParams.age);
      formData.append('gender', this.riskParams.gender);
      formData.append('exposureTime', this.riskParams.exposureTime);

      try {
        // 上传CT
        const uploadResponse = await axios.post(
          `${API_BASE}/api/wholebody/upload-patient-ct`, 
          formData
        );
        const sessionId = uploadResponse.data.sessionId;

        // 运行评估
        await axios.post(`${API_BASE}/api/wholebody/run-assessment`, {
          sessionId,
          ...this.riskParams
        });

        // 轮询状态
        const checkStatus = async () => {
          const statusResponse = await axios.get(
            `${API_BASE}/api/wholebody/assessment-status/${sessionId}`
          );
          
          if (statusResponse.data.status === 'completed') {
            // 获取结果
            const resultsResponse = await axios.get(
              `${API_BASE}/api/wholebody/report/${sessionId}`
            );
            this.riskResults = resultsResponse.data;

            // 获取可视化
            const vizResponse = await axios.get(
              `${API_BASE}/api/wholebody/visualization/${sessionId}`
            );
            this.riskVisualization = vizResponse.data.visualizationPath 
              ? `${API_BASE}${vizResponse.data.visualizationPath}` 
              : '';

            this.showMessage('风险评估完成', 'success');
            this.loading = false;
          } else if (statusResponse.data.status === 'error') {
            throw new Error('评估失败');
          } else {
            setTimeout(checkStatus, 2000);
          }
        };

        await checkStatus();
      } catch (error) {
        this.showMessage('评估失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
        this.loading = false;
      }
    },

    getRiskLevel(risk) {
      if (risk < 0.001) return 'low';
      if (risk < 0.01) return 'medium';
      return 'high';
    },

  }
};
</script>

<style scoped>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.bnct-platform {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  color: #333;
}

/* ========== 顶部导航 ========== */
.platform-header {
  background: white;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
  padding: 1rem 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo-section h1 {
  font-size: 1.8rem;
  color: #667eea;
  margin: 0;
}

.version {
  background: #667eea;
  color: white;
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.8rem;
}

.nav-tabs {
  display: flex;
  gap: 0.5rem;
}

.nav-tab {
  padding: 0.8rem 1.5rem;
  border: none;
  background: #f5f5f5;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.3s;
  font-size: 1rem;
  font-weight: 500;
}

.nav-tab:hover {
  background: #e0e0e0;
  transform: translateY(-2px);
}

.nav-tab.active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

/* ========== 主内容区 ========== */
.main-content {
  padding: 2rem;
  max-width: 1800px;
  margin: 0 auto;
}

.tab-content {
  background: white;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  animation: fadeIn 0.5s;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ========== 工作区布局 ========== */
.workspace {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 2rem;
  min-height: 700px;
}

/* ========== 控制面板 ========== */
.control-panel {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 1.5rem;
  height: fit-content;
}

.panel-section {
  margin-bottom: 2rem;
  padding-bottom: 2rem;
  border-bottom: 1px solid #e0e0e0;
}

.panel-section:last-child {
  border-bottom: none;
}

.panel-section h3 {
  color: #667eea;
  margin-bottom: 1rem;
  font-size: 1.1rem;
}

.btn {
  padding: 0.8rem 1.5rem;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.95rem;
  font-weight: 500;
  transition: all 0.3s;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  justify-content: center;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-secondary {
  background: #e0e0e0;
  color: #333;
}

.btn-secondary:hover:not(:disabled) {
  background: #d0d0d0;
}

.btn-success {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: white;
}

.btn-success:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(17, 153, 142, 0.4);
}

.btn-large {
  padding: 1rem 2rem;
  font-size: 1.1rem;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon {
  font-size: 1.2rem;
}

.file-info {
  margin-top: 1rem;
  padding: 1rem;
  background: white;
  border-radius: 6px;
  font-size: 0.9rem;
}

.info-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.label {
  color: #666;
  font-weight: 500;
}

.value {
  color: #333;
}

.status-success {
  color: #11998e;
  font-weight: 600;
}

/* ========== 视图控制 ========== */
.view-controls {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.control-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.control-item label {
  font-size: 0.9rem;
  color: #666;
  font-weight: 500;
}

.slider {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: #e0e0e0;
  outline: none;
  -webkit-appearance: none;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #667eea;
  cursor: pointer;
}

.slice-number {
  font-size: 0.85rem;
  color: #999;
  text-align: right;
}

/* ========== 影像查看器 ========== */
.image-viewer {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.viewer-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.viewer-panel {
  background: #f9f9f9;
  border-radius: 8px;
  overflow: hidden;
}

.panel-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 0.8rem 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h4 {
  margin: 0;
  font-size: 1rem;
}

.panel-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-icon {
  background: rgba(255,255,255,0.2);
  border: none;
  color: white;
  width: 30px;
  height: 30px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.3s;
  font-size: 1rem;
}

.btn-icon:hover {
  background: rgba(255,255,255,0.3);
}

.image-container {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.medical-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.dose-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
  mix-blend-mode: screen;
}

.placeholder {
  text-align: center;
  color: #999;
  padding: 2rem;
}

.placeholder p:first-child {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.crosshair {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.crosshair-h, .crosshair-v {
  position: absolute;
  background: rgba(0, 255, 0, 0.5);
}

.crosshair-h {
  top: 50%;
  left: 0;
  width: 100%;
  height: 1px;
}

.crosshair-v {
  top: 0;
  left: 50%;
  width: 1px;
  height: 100%;
}

.image-info {
  padding: 0.5rem 1rem;
  background: white;
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  color: #666;
}

.dose-control-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: #f9f9f9;
  border-radius: 6px;
}

.dose-control-bar label {
  font-weight: 500;
  color: #666;
}

/* ========== MCNP工作流 ========== */
.mcnp-workspace {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 2rem;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.workflow-step {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 1.5rem;
  display: grid;
  grid-template-columns: 50px 1fr 50px;
  gap: 1rem;
  align-items: start;
  transition: all 0.3s;
  border: 2px solid transparent;
}

.workflow-step.active {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
}

.workflow-step.completed {
  border-color: #11998e;
}

.workflow-step.error {
  border-color: #e74c3c;
}

.step-number {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: bold;
}

.workflow-step.completed .step-number {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
}

.step-content h4 {
  margin-bottom: 0.5rem;
  color: #333;
}

.step-content p {
  color: #666;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}

.progress-bar {
  width: 100%;
  height: 6px;
  background: #e0e0e0;
  border-radius: 3px;
  overflow: hidden;
  margin-top: 0.5rem;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  transition: width 0.3s;
}

.step-result {
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: white;
  border-radius: 4px;
  font-size: 0.9rem;
  color: #11998e;
}

.step-status {
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
}

.status-icon.success {
  background: #d4edda;
  color: #11998e;
}

.status-icon.error {
  background: #f8d7da;
  color: #e74c3c;
}

.status-icon.active {
  background: #d1ecf1;
  color: #667eea;
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ========== 日志面板 ========== */
.log-panel {
  background: #f9f9f9;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 600px;
}

.log-header {
  background: #333;
  color: white;
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-header h4 {
  margin: 0;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
  background: #2c3e50;
  color: #ecf0f1;
}

.log-entry {
  padding: 0.5rem;
  margin-bottom: 0.3rem;
  border-left: 3px solid #3498db;
  background: rgba(255,255,255,0.05);
}

.log-entry.success {
  border-color: #2ecc71;
}

.log-entry.error {
  border-color: #e74c3c;
}

.log-time {
  color: #95a5a6;
  margin-right: 0.5rem;
}

.log-empty {
  text-align: center;
  color: #95a5a6;
  padding: 2rem;
}

/* ========== 剂量工作区样式 ========== */
.dose-workspace {
  display: flex;
  gap: 20px;
  height: calc(100vh - 200px);
  padding: 20px;
}

.dose-control-panel {
  width: 320px;
  background: #f8f9fa;
  border-radius: 8px;
  padding: 20px;
  overflow-y: auto;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.dose-viewer {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 剂量切片导航按钮 */
.slice-nav-buttons {
  display: flex;
  gap: 6px;
  margin-top: 4px;
  padding: 4px 8px;
  justify-content: center;
  flex-shrink: 0;
}

.nav-btn {
  padding: 4px 10px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
}

.nav-btn:hover:not(:disabled) {
  background: #4a90e2;
  color: white;
  border-color: #4a90e2;
  transform: translateY(-1px);
}

.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #f5f5f5;
}

/* 切片信息叠加 */
.slice-info-overlay {
  position: absolute;
  top: 10px;
  left: 10px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  backdrop-filter: blur(4px);
}

/* 统计信息网格 */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: 12px;
  background: white;
  border-radius: 6px;
  border: 1px solid #e0e0e0;
  transition: all 0.2s;
}

.stat-item:hover {
  border-color: #4a90e2;
  box-shadow: 0 2px 4px rgba(74, 144, 226, 0.1);
}

.stat-label {
  color: #666;
  font-size: 13px;
}

.stat-value {
  font-weight: bold;
  color: #4a90e2;
  font-size: 14px;
}

/* 色图渐变 */
.colorbar-section {
  padding: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.colorbar {
  margin: 10px 0;
}

.colorbar-gradient {
  height: 30px;
  border-radius: 4px;
  margin-bottom: 8px;
}

.colorbar-gradient.hot {
  background: linear-gradient(to right, 
    #000000, #800000, #ff0000, #ff8000, #ffff00, #ffffff);
}

.colorbar-gradient.jet {
  background: linear-gradient(to right, 
    #0000ff, #0080ff, #00ffff, #00ff00, #ffff00, #ff8000, #ff0000);
}

.colorbar-gradient.viridis {
  background: linear-gradient(to right, 
    #440154, #31688e, #35b779, #fde724);
}

.colorbar-gradient.plasma {
  background: linear-gradient(to right, 
    #0d0887, #7e03a8, #cc4778, #f89540, #f0f921);
}

.colorbar-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #666;
}

/* 选择框样式 */
.select-box {
  width: 100%;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.select-box:hover {
  border-color: #4a90e2;
}

.select-box:focus {
  outline: none;
  border-color: #4a90e2;
  box-shadow: 0 0 0 2px rgba(74, 144, 226, 0.1);
}

/* 按钮块级样式 */
.btn-block {
  width: 100%;
  margin-bottom: 10px;
}

/* 提示文本 */
.hint-small {
  font-size: 11px;
  color: #999;
  margin-top: 5px;
  text-align: center;
}

/* 剂量图像容器 */
/* ===== 剂量视图网格 ===== */

.dose-viewer-grid {
  display: flex;
  gap: 0.8rem;
  height: calc(100vh - 280px);
  min-height: 400px;
}

/* 三个面板等宽 */
.dose-panel {
  flex: 1 1 0;
  min-width: 0;
  background: #1a1a2e;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  display: flex;
  flex-direction: column;
}

.dose-panel--axial,
.dose-panel--coronal,
.dose-panel--sagittal {
  /* 全部等宽，由 flex: 1 1 0 控制 */
}

/* 图像区域填满面板剩余空间 */
.dose-image-wrapper {
  position: relative;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex: 1;
  min-height: 0;
}

.dose-image-wrapper--axial,
.dose-image-wrapper--coronal,
.dose-image-wrapper--sagittal {
  /* 不设固定宽高比 */
}

/* 图片在黑色容器内按原始比例缩放，不拉伸不压缩 */
.dose-image-wrapper .dose-image {
  display: block;
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}

/* 旧的通用兼容 */
.dose-image-container {
  position: relative;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.dose-image {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

/* ========== DVH分析 ========== */
.dvh-workspace {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 2rem;
}

.dvh-controls {
  background: #f9f9f9;
  padding: 1.5rem;
  border-radius: 8px;
  height: fit-content;
}

.dvh-controls h3 {
  color: #667eea;
  margin-bottom: 1rem;
}

.organ-list {
  margin: 1.5rem 0;
}

.organ-list h4 {
  margin-bottom: 0.8rem;
  font-size: 0.95rem;
}

.organ-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem;
  background: white;
  border-radius: 4px;
  margin-bottom: 0.5rem;
}

.organ-name {
  font-size: 0.9rem;
  color: #333;
}

.dvh-display {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.dvh-chart {
  background: #f9f9f9;
  padding: 2rem;
  border-radius: 8px;
  text-align: center;
}

.dvh-chart h3 {
  color: #667eea;
  margin-bottom: 1.5rem;
}

.dvh-img {
  max-width: 100%;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
}

.placeholder-large {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 4rem;
  text-align: center;
  color: #999;
}

.placeholder-large p:first-child {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.placeholder-large .hint {
  font-size: 0.9rem;
}

.dvh-stats {
  background: #f9f9f9;
  padding: 2rem;
  border-radius: 8px;
}

.dvh-stats h4 {
  color: #667eea;
  margin-bottom: 1rem;
}

.stats-table {
  width: 100%;
  border-collapse: collapse;
  background: white;
  border-radius: 4px;
  overflow: hidden;
}

.stats-table th,
.stats-table td {
  padding: 0.8rem;
  text-align: left;
  border-bottom: 1px solid #e0e0e0;
}

.stats-table th {
  background: #667eea;
  color: white;
  font-weight: 600;
}

.stats-table tr:last-child td {
  border-bottom: none;
}

/* ========== 风险评估 ========== */
.risk-workspace {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2rem;
}

.risk-assessment-panel {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.risk-assessment-panel h3 {
  color: #667eea;
  margin-bottom: 1rem;
}

.assessment-steps {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.step {
  background: #f9f9f9;
  padding: 1.5rem;
  border-radius: 8px;
}

.step h4 {
  color: #333;
  margin-bottom: 1rem;
}

.param-group {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.param-group label {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.param-group input,
.param-group select {
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 4px;
  width: 60%;
}

.risk-results {
  background: #f9f9f9;
  padding: 2rem;
  border-radius: 8px;
}

.result-card {
  background: white;
  padding: 2rem;
  border-radius: 8px;
  text-align: center;
  margin-bottom: 2rem;
}

.risk-score {
  font-size: 3rem;
  font-weight: bold;
  margin: 1rem 0;
}

.risk-score.low {
  color: #2ecc71;
}

.risk-score.medium {
  color: #f39c12;
}

.risk-score.high {
  color: #e74c3c;
}

.risk-description {
  color: #666;
  font-size: 1.1rem;
}

.organ-risks h4 {
  color: #667eea;
  margin-bottom: 1rem;
}

.organ-risk-bar {
  display: grid;
  grid-template-columns: 150px 1fr 80px;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.8rem;
}

.organ-label {
  font-weight: 500;
  color: #333;
}

.risk-bar-container {
  background: #e0e0e0;
  height: 24px;
  border-radius: 12px;
  overflow: hidden;
}

.risk-bar-fill {
  height: 100%;
  transition: width 0.5s;
  border-radius: 12px;
}

.risk-bar-fill.low {
  background: linear-gradient(90deg, #2ecc71 0%, #27ae60 100%);
}

.risk-bar-fill.medium {
  background: linear-gradient(90deg, #f39c12 0%, #e67e22 100%);
}

.risk-bar-fill.high {
  background: linear-gradient(90deg, #e74c3c 0%, #c0392b 100%);
}

.risk-value {
  text-align: right;
  font-weight: 600;
  color: #333;
}

.risk-visualization h4 {
  color: #667eea;
  margin-bottom: 1rem;
}

.viz-container {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 2rem;
}

.risk-3d-view {
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.risk-3d-view img {
  width: 100%;
  display: block;
}

/* ========== 消息提示 ========== */
.message-toast {
  position: fixed;
  top: 100px;
  right: 2rem;
  background: white;
  padding: 1rem 1.5rem;
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.2);
  display: flex;
  align-items: center;
  gap: 1rem;
  z-index: 1000;
  min-width: 300px;
}

.message-toast.success {
  border-left: 4px solid #2ecc71;
}

.message-toast.error {
  border-left: 4px solid #e74c3c;
}

.message-toast.info {
  border-left: 4px solid #3498db;
}

.toast-icon {
  font-size: 1.5rem;
}

.toast-message {
  flex: 1;
  color: #333;
}

.toast-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #999;
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fade-enter-active, .fade-leave-active {
  transition: all 0.3s;
}

.fade-enter-from {
  opacity: 0;
  transform: translateX(100px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateX(100px);
}

/* ========== 加载遮罩 ========== */
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0,0,0,0.7);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.spinner {
  width: 60px;
  height: 60px;
  border: 4px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-overlay p {
  color: white;
  margin-top: 1rem;
  font-size: 1.1rem;
}

/* ========== 响应式设计 ========== */
@media (max-width: 1400px) {
  .workspace {
    grid-template-columns: 250px 1fr;
  }

  .viewer-grid,
  .viz-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dose-viewer-grid {
    gap: 0.5rem;
  }
}

@media (max-width: 1024px) {
  .workspace,
  .mcnp-workspace,
  .dvh-workspace,
  .risk-workspace {
    grid-template-columns: 1fr;
  }

  .viewer-grid,
  .viz-grid {
    grid-template-columns: 1fr;
  }

  .dose-viewer-grid {
    flex-direction: column;
    height: auto;
  }

  .nav-tabs {
    flex-wrap: wrap;
  }

  .dose-workspace {
    flex-direction: column;
    height: auto;
  }
  
  .dose-control-panel {
    width: 100%;
  }
}

@media (max-width: 768px) {
  .platform-header {
    flex-direction: column;
    gap: 1rem;
  }

  .main-content {
    padding: 1rem;
  }

  .tab-content {
    padding: 1rem;
  }

  .dose-viewer-grid {
    flex-direction: column;
    height: auto;
  }
}
</style>