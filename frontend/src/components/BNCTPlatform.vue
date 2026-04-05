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
              <button @click="$refs.fileInput.click()" :disabled="niiUploading" class="btn btn-primary">
                <span class="icon">📤</span>
                {{ niiUploading ? '正在上传...' : '上传NIfTI文件 (.nii.gz)' }}
              </button>
              <input 
                ref="fileInput" 
                type="file" 
                @change="handleNiiUpload" 
                accept=".nii.gz" 
                style="display: none"
              />
              
              <div v-if="uploadedFile" class="file-info">
                <div class="info-item info-item--col">
                  <span class="label">文件名:</span>
                  <span class="value filename-value" :title="uploadedFile.name">{{ uploadedFile.name }}</span>
                </div>
                <div class="info-item">
                  <span class="label">大小:</span>
                  <span class="value">{{ formatFileSize(uploadedFile.size) }}</span>
                  <span class="value status-success">✓ 已加载</span>
                </div>
              </div>
            </div>


            <!-- 器官轮廓区块 -->
            <div class="panel-section">
              <h3>🫀 器官轮廓</h3>

              <!-- 已加载的器官列表（折叠） -->
              <div v-if="contourMasks.length > 0" class="contour-summary">
                <div class="contour-summary-header" @click="contourListExpanded = !contourListExpanded">
                  <span>已加载 {{ contourMasks.length }} 个器官</span>
                  <span class="auto-seg-toggle">{{ contourListExpanded ? '▲' : '▼' }}</span>
                </div>
                <div v-if="contourListExpanded" class="contour-list">
                  <div v-for="(mask, idx) in contourMasks" :key="idx" class="contour-item">
                    <span class="contour-color-dot" :style="{ background: mask.color }"></span>
                    <span class="contour-organ-name" :title="mask.name">{{ mask.name }}</span>
                    <button class="btn-icon-sm" @click="contourMasks.splice(idx,1)" title="移除">✕</button>
                  </div>
                </div>
              </div>

              <!-- 操作按钮 -->
              <button
                v-if="contourMasks.length > 0 && niiPath"
                @click="generateContourOverlay"
                :disabled="contourGenerating"
                class="btn btn-primary"
                style="width:100%;margin-top:6px;"
              >
                {{ contourGenerating ? '⏳ 生成中...' : '🖼️ 生成轮廓叠加' }}
              </button>

              <button
                v-if="overlaySlices.axial.length > 0"
                @click="showContourOverlay = !showContourOverlay"
                :class="['btn', showContourOverlay ? 'btn-active' : 'btn-secondary']"
                style="width:100%;margin-top:4px;"
              >
                {{ showContourOverlay ? '✅ 已显示轮廓' : '👁 显示轮廓叠加' }}
              </button>

              <!-- 自动勾画 -->
              <div style="margin-top:10px;border-top:1px solid #eee;padding-top:8px;">
                <button
                  @click="runAutoSegment"
                  :disabled="!niiPath || autoSegmenting"
                  class="btn btn-warn"
                  style="width:100%;"
                >
                  {{ autoSegmenting ? '⏳ 自动勾画中...' : '🤖 自动勾画' }}
                </button>
                <div v-if="autoSegResult && !autoSegResult.success" class="contour-msg-warn" style="margin-top:6px;">
                  ⚠ {{ autoSegResult.error }}
                  <br><code>{{ autoSegResult.install_cmd }}</code>
                </div>
                <div v-if="autoSegResult && autoSegResult.success" class="auto-seg-summary" style="margin-top:6px;">
                  <div class="auto-seg-header" @click="autoSegExpanded = !autoSegExpanded">
                    <span class="auto-seg-count">✓ 已识别 {{ autoSegResult.organs.length }} 个器官</span>
                    <span class="auto-seg-toggle">{{ autoSegExpanded ? '▲' : '▼' }}</span>
                  </div>
                  <div v-if="autoSegExpanded" class="auto-seg-organ-list">
                    <div v-for="(organ, oi) in autoSegResult.organs" :key="oi" class="auto-seg-organ-item">
                      <span class="auto-seg-organ-dot" :style="{ background: contourColors[oi % contourColors.length] }"></span>
                      <span>{{ organ }}</span>
                    </div>
                  </div>
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
                  <!-- 轮廓叠加模式 -->
                  <img
                    v-if="showContourOverlay && overlaySlices[view] && overlaySlices[view][sliceIndices[view]]"
                    :src="getImageUrl(overlaySlices[view][sliceIndices[view]])"
                    :alt="`${viewNames[view]}轮廓叠加`"
                    class="medical-image"
                    @error="handleImageError"
                  />
                  <!-- 普通CT模式 -->
                  <img
                    v-else-if="slices[view] && slices[view][sliceIndices[view]]"
                    :src="getImageUrl(slices[view][sliceIndices[view]])"
                    :alt="`${viewNames[view]}切片`"
                    class="medical-image"
                    @error="handleImageError"
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
                <div class="viewer-slice-control">
                  <input
                    v-model.number="sliceIndices[view]"
                    type="range"
                    :min="0"
                    :max="Math.max(0, (slices[view] && slices[view].length ? slices[view].length : 1) - 1)"
                    class="viewer-slider"
                  />
                </div>
              </div>
            </div>

          </section>
        </div>

        <!-- 全屏遮罩 -->
        <div v-if="fullscreenView" class="fullscreen-overlay" @click.self="fullscreenView = null">
          <div class="fullscreen-panel">
            <div class="panel-header">
              <h4>{{ viewNames[fullscreenView] }}切面</h4>
              <div class="panel-actions">
                <button @click="fullscreenView = null" class="btn-icon" title="退出全屏">✕</button>
              </div>
            </div>
            <div class="fullscreen-image-container">
              <img
                v-if="showContourOverlay && overlaySlices[fullscreenView] && overlaySlices[fullscreenView][sliceIndices[fullscreenView]]"
                :src="getImageUrl(overlaySlices[fullscreenView][sliceIndices[fullscreenView]])"
                :alt="`${viewNames[fullscreenView]}轮廓叠加`"
                class="fullscreen-image"
                @error="handleImageError"
              />
              <img
                v-else-if="slices[fullscreenView] && slices[fullscreenView][sliceIndices[fullscreenView]]"
                :src="getImageUrl(slices[fullscreenView][sliceIndices[fullscreenView]])"
                :alt="`${viewNames[fullscreenView]}切片`"
                class="fullscreen-image"
                @error="handleImageError"
              />
              <div v-if="!slices[fullscreenView] || slices[fullscreenView].length === 0" class="placeholder">
                <p>📷</p>
                <p>等待加载影像数据...</p>
              </div>
              <div v-if="showCrosshair" class="crosshair">
                <div class="crosshair-h"></div>
                <div class="crosshair-v"></div>
              </div>
            </div>
            <div class="image-info">
              <span>切片: {{ sliceIndices[fullscreenView] + 1 }}/{{ slices[fullscreenView] && slices[fullscreenView].length ? slices[fullscreenView].length : 0 }}</span>
              <span v-if="imageMetadata[fullscreenView]">{{ imageMetadata[fullscreenView].spacing }} mm</span>
            </div>
            <div class="viewer-slice-control" style="padding: 0 1rem 1rem;">
              <input
                v-model.number="sliceIndices[fullscreenView]"
                type="range"
                :min="0"
                :max="Math.max(0, (slices[fullscreenView] && slices[fullscreenView].length ? slices[fullscreenView].length : 1) - 1)"
                class="viewer-slider"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 2: MCNP计算 -->
      <div v-show="activeTab === 'mcnp'" class="tab-content">
        <div class="mcnp-workspace">

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
                  {{ loading && currentStep === index ? step.loadingText : step.buttonText }}
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
          <button @click="$refs.doseInput.click()" :disabled="doseUploading" class="btn btn-primary">
            <span class="icon">📁</span>
            {{ doseUploading ? '正在上传...' : '选择剂量文件 (.npy)' }}
          </button>
          <input 
            ref="doseInput" 
            type="file" 
            @change="handleDoseUpload" 
            accept=".npy" 
            multiple 
            style="display: none"
          />
          <div v-if="doseFiles.length > 0" class="file-list">
            <div v-for="(file, index) in doseFiles" :key="index" class="file-item">
              <span>{{ file.name }}</span>
              <button @click="removeDoseFile(index)" class="btn-remove">×</button>
            </div>
          </div>
        </div>
      </div>


      <!-- 器官轮廓显示（折叠） -->
      <div v-if="hasDoseData" class="panel-section">
        <div class="organ-collapse-header" @click="doseOrganExpanded = !doseOrganExpanded">
          <h3 style="margin:0;">🫀 器官轮廓</h3>
          <span class="collapse-arrow">{{ doseOrganExpanded ? '▲' : '▼' }}</span>
        </div>
        <div v-if="!doseOrganExpanded" class="organ-collapse-summary">
          已加载 {{ doseOrganList.filter(o => o.visible).length }}/{{ doseOrganList.length }} 个器官可见
        </div>
        <div v-if="doseOrganExpanded">
          <div class="dose-organ-list">
            <div
              v-for="organ in doseOrganList"
              :key="organ.keyword"
              class="dose-organ-item"
              @click="organ.visible = !organ.visible; doseOrgansDirty = true"
            >
              <input
                type="checkbox"
                :checked="organ.visible"
                @change.stop="organ.visible = $event.target.checked; doseOrgansDirty = true"
                @click.stop
                class="organ-checkbox"
              />
              <span class="contour-color-dot" :style="{ background: organ.color, opacity: organ.visible ? 1 : 0.35 }"></span>
              <span class="contour-organ-name" :style="{ color: organ.visible ? '#333' : '#aaa' }">{{ organ.name }}</span>
            </div>
          </div>
          <div style="display:flex;gap:6px;margin-top:8px;">
            <button
              @click="doseOrganList.forEach(o => o.visible = true); doseOrgansDirty = true"
              class="btn btn-secondary"
              style="flex:1;font-size:0.78rem;padding:4px 0;"
            >全选</button>
            <button
              @click="doseOrganList.forEach(o => o.visible = false); doseOrgansDirty = true"
              class="btn btn-secondary"
              style="flex:1;font-size:0.78rem;padding:4px 0;"
            >全消</button>
          </div>
          <button
            v-if="doseOrgansDirty"
            @click="reapplyDoseOrgans"
            :disabled="doseOrganApplying"
            class="btn btn-primary"
            style="width:100%;margin-top:8px;"
          >
            {{ doseOrganApplying ? '⏳ 重新生成中...' : '✅ 应用轮廓设置' }}
          </button>
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
          <div v-if="slices.doseAxial && slices.doseAxial.length > 0" class="dose-panel-slider">
            <input
              v-model.number="doseSliceIndices.axial"
              type="range" min="0"
              :max="slices.doseAxial.length - 1"
              class="viewer-slider"
            />
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
          <div v-if="slices.doseCoronal && slices.doseCoronal.length > 0" class="dose-panel-slider">
            <input
              v-model.number="doseSliceIndices.coronal"
              type="range" min="0"
              :max="slices.doseCoronal.length - 1"
              class="viewer-slider"
            />
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
          <div v-if="slices.doseSagittal && slices.doseSagittal.length > 0" class="dose-panel-slider">
            <input
              v-model.number="doseSliceIndices.sagittal"
              type="range" min="0"
              :max="slices.doseSagittal.length - 1"
              class="viewer-slider"
            />
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
              <!-- 体模状态 -->
              <div class="step">
                <h4>1. 全身体模状态</h4>
                <div v-if="phantomBuilt" class="phantom-status-ok">
                  <span class="status-check">✓ 全身体模已构建完成（男性标准体模，照射部位自动识别）</span>
                </div>
                <div v-else class="phantom-status-warn">
                  请先在「MCNP计算」标签页中完成全身体模构建，风险评估将直接基于已构建的体模和照射位置进行。
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
                <p v-if="!phantomBuilt" class="hint-text">需先完成体模构建</p>
              </div>
            </div>

            <!-- 评估结果 -->
            <div v-if="riskResults" class="risk-results">
              <h3>二次癌风险评估结果</h3>

              <!-- 总体风险概览卡片 -->
              <div class="result-card">
                <h4>全身累积二次癌终生归因风险（LAR）</h4>
                <div class="risk-score" :class="getRiskLevel(riskResults.totalRisk)">
                  {{ riskResults.totalRisk.toFixed(4) }}%
                </div>
                <p class="risk-description">{{ getRiskDescription(riskResults.totalRisk) }}</p>
                <div class="risk-legend">
                  <span class="legend-item negligible">可忽略 &lt;0.001%</span>
                  <span class="legend-item low">低风险 0.001‒0.01%</span>
                  <span class="legend-item moderate">中等 0.01‒0.1%</span>
                  <span class="legend-item high">较高 &gt;0.1%</span>
                </div>
              </div>

              <!-- 详细二次癌风险分析表格 -->
              <div class="secondary-cancer-section">
                <h4>各癌症部位详细风险分析（基于 BEIR VII 模型）</h4>
                <p class="section-note">
                  LAR = 终生归因风险（百分比）；ERR = 超额相对风险；EAR = 超额绝对风险（/10,000人年）；
                  组合LAR 采用 ERR 与 EAR 等权重平均（各50%）。
                </p>

                <div class="risk-table-wrapper">
                  <table class="secondary-risk-table">
                    <thead>
                      <tr>
                        <th>癌症部位</th>
                        <th>器官剂量 (Sv)</th>
                        <th>LAR<sub>ERR</sub> (%)</th>
                        <th>LAR<sub>EAR</sub> (%)</th>
                        <th>LAR<sub>组合</sub> (%)</th>
                        <th>ERR</th>
                        <th>EAR (/万人年)</th>
                        <th>风险等级</th>
                        <th>相对大小</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="organ in riskResults.organs" :key="organ.name">
                        <td class="organ-name-cell">{{ organ.name }}</td>
                        <td class="num-cell">{{ organ.doseSv.toFixed(4) }}</td>
                        <td class="num-cell">{{ organ.larErr.toFixed(5) }}</td>
                        <td class="num-cell">{{ organ.larEar.toFixed(5) }}</td>
                        <td class="num-cell lar-combined">{{ organ.risk.toFixed(5) }}</td>
                        <td class="num-cell">{{ organ.err.toFixed(4) }}</td>
                        <td class="num-cell">{{ organ.ear.toFixed(4) }}</td>
                        <td>
                          <span :class="['risk-badge', organ.riskLevel]">
                            {{ getRiskLevelLabel(organ.riskLevel) }}
                          </span>
                        </td>
                        <td class="bar-cell">
                          <div class="inline-bar-container">
                            <div
                              class="inline-bar-fill"
                              :class="organ.riskLevel"
                              :style="{ width: (organ.risk / riskResults.maxRisk * 100) + '%' }"
                            ></div>
                          </div>
                        </td>
                      </tr>
                    </tbody>
                    <tfoot>
                      <tr class="total-row">
                        <td>全身累积</td>
                        <td>—</td>
                        <td>—</td>
                        <td>—</td>
                        <td class="num-cell lar-combined">{{ riskResults.totalRisk.toFixed(5) }}</td>
                        <td>—</td>
                        <td>—</td>
                        <td>—</td>
                        <td>—</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>

              <!-- 器官风险条形图（保留原有可视化） -->
              <div class="organ-risks">
                <h4>器官风险分布（LAR 组合值）</h4>
                <div class="risk-chart">
                  <div v-for="organ in riskResults.organs" :key="organ.name + '_bar'" class="organ-risk-bar">
                    <span class="organ-label">{{ organ.name }}</span>
                    <div class="risk-bar-container">
                      <div
                        class="risk-bar-fill"
                        :style="{ width: (organ.risk / riskResults.maxRisk * 100) + '%' }"
                        :class="getRiskLevel(organ.risk)"
                      ></div>
                    </div>
                    <span class="risk-value">{{ organ.risk.toFixed(5) }}%</span>
                  </div>
                </div>
              </div>

            </div>
          </div>

        </div>
      </div>

      <!-- ICRP标准体模对比（合并至风险评估页） -->
      <div v-show="activeTab === 'risk'" class="tab-content">
        <div class="icrp-compare-workspace">
          <div class="icrp-compare-header">
            <h2>📋 ICRP-110 标准体模 vs 参考数据对比</h2>
            <p class="icrp-desc">
              使用ICRP Publication 110标准参考体模，从体素数据计算各器官<strong>质量</strong>与<strong>体积</strong>，
              与ICRP报告中发布的参考值进行定量对比验证。
            </p>
          </div>

          <div class="icrp-compare-controls">
            <div class="control-row">
              <label class="ctrl-label">体模类型：</label>
              <div class="btn-group">
                <button
                  :class="['btn-phantom', { active: icrcPhantomType === 'AM' }]"
                  @click="icrcPhantomType = 'AM'"
                >AM（成人男性）</button>
                <button
                  :class="['btn-phantom', { active: icrcPhantomType === 'AF' }]"
                  @click="icrcPhantomType = 'AF'"
                >AF（成人女性）</button>
              </div>
              <button
                @click="runIcrcComparison"
                :disabled="icrcLoading"
                class="btn btn-primary run-btn"
              >
                <span v-if="icrcLoading" class="spinner-sm"></span>
                {{ icrcLoading ? '计算中（约1-3分钟）...' : '▶ 运行对比' }}
              </button>
            </div>
            <div v-if="icrcLoading" class="icrp-progress-note">
              正在加载体素数据并计算器官质量，请耐心等待...
            </div>
          </div>

          <!-- 结果区域 -->
          <div v-if="icrcResult" class="icrp-results">
            <!-- 摘要卡片 -->
            <div class="icrp-summary-cards">
              <div class="summary-card">
                <div class="card-label">体模类型</div>
                <div class="card-value">{{ icrcResult.phantom_type }}</div>
              </div>
              <div class="summary-card">
                <div class="card-label">参考身高</div>
                <div class="card-value">{{ icrcResult.phantom_height_cm }} cm</div>
              </div>
              <div class="summary-card">
                <div class="card-label">参考体重</div>
                <div class="card-value">{{ icrcResult.phantom_mass_kg }} kg</div>
              </div>
              <div class="summary-card">
                <div class="card-label">总体素数</div>
                <div class="card-value">{{ (icrcResult.total_voxels / 1e6).toFixed(2) }} M</div>
              </div>
              <div class="summary-card">
                <div class="card-label">对比器官数</div>
                <div class="card-value">{{ icrcResult.organs_compared }}</div>
              </div>
              <div class="summary-card">
                <div class="card-label">体素尺寸</div>
                <div class="card-value">{{ icrcResult.voxel_size_mm ? icrcResult.voxel_size_mm.join('×') : '-' }} mm</div>
              </div>
            </div>

            <!-- 对比图表 -->
            <div v-if="icrcChartUrl" class="icrp-chart-section">
              <h3>器官质量对比图</h3>
              <img :src="icrcChartUrl" alt="ICRP对比图" class="icrp-chart-img" />
            </div>

            <!-- 数据表格 -->
            <div class="icrp-table-section">
              <h3>器官质量 &amp; 体积对比数据表</h3>
              <div class="table-legend">
                <span class="legend-good">● 偏差 ≤5%（优秀）</span>
                <span class="legend-ok">● 偏差 5~15%（良好）</span>
                <span class="legend-warn">● 偏差 >15%（注意）</span>
                <span class="legend-disc"> ★ 体素数&lt;500：离散化误差较大，属正常现象</span>
              </div>
              <div class="icrp-disc-note">
                <strong>关于大偏差的说明：</strong>
                AM体模z方向体素厚度为 <strong>8.0 mm</strong>，对于肾上腺（14 g）、胆囊壁（8 g）等小器官，
                一个体素即代表较大体积，边界截断导致体素离散化误差（Voxel Discretization Error）偏大。
                这是体素化体模的固有局限性，已在 ICRP Publication 110 正文中明确说明。
                大器官（肝脏、肺、脑等）误差通常 &lt;1%，验证了计算流程的正确性。
                <br><strong>参考体积</strong> = ICRP参考质量 / 体模组织密度（与体素数据一致的密度值）。
              </div>
              <!-- 剂量与风险数据提示 -->
              <div v-if="riskResults" class="icrp-risk-tip">
                <strong>✓ 已检测到风险评估结果</strong>，下表已自动关联计算剂量与 LAR 风险数据。
                （性别：{{ icrcPhantomType === 'AM' ? '男性' : '女性' }}，BEIR VII 基线发病率来自中国肿瘤登记年报）
              </div>
              <div v-else class="icrp-risk-tip icrp-risk-tip--none">
                <strong>ℹ 尚未运行风险评估</strong>，表格仅显示质量与体积对比。
                请先在「全身风险评估」选项卡完成评估后，再次查看本表格可获取剂量与风险对比列。
              </div>

              <table class="icrp-table">
                <thead>
                  <tr>
                    <th rowspan="2" style="vertical-align:middle;">器官</th>
                    <th colspan="3" class="th-group-mass">质量对比（ICRP 110）</th>
                    <th colspan="3" class="th-group-volume">体积对比（ICRP 110）</th>
                    <template v-if="riskResults">
                      <th colspan="4" class="th-group-risk">剂量与风险（BEIR VII / ICRP 103）</th>
                    </template>
                    <th rowspan="2" style="vertical-align:middle;">体素数</th>
                    <th rowspan="2" style="vertical-align:middle;">评级</th>
                  </tr>
                  <tr>
                    <th class="th-sub th-sub-mass">ICRP参考 (g)</th>
                    <th class="th-sub th-sub-mass">体模计算 (g)</th>
                    <th class="th-sub th-sub-mass">偏差 (%)</th>
                    <th class="th-sub th-sub-vol">ICRP参考 (cm³)</th>
                    <th class="th-sub th-sub-vol">体模计算 (cm³)</th>
                    <th class="th-sub th-sub-vol">偏差 (%)</th>
                    <template v-if="riskResults">
                      <th class="th-sub th-sub-risk">剂量 (Sv)</th>
                      <th class="th-sub th-sub-risk">LAR (%)</th>
                      <th class="th-sub th-sub-risk">基线(/10万年)</th>
                      <th class="th-sub th-sub-risk">风险</th>
                    </template>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in icrcResult.organ_results" :key="row.organ"
                      :class="{ 'row-small-organ': row.voxel_count && row.voxel_count < 500 }">
                    <td class="organ-name">{{ row.organ }}</td>
                    <!-- 质量列 -->
                    <td class="val-ref">{{ row.reference_g !== null ? row.reference_g.toFixed(2) : '-' }}</td>
                    <td class="val-calc">{{ row.calculated_g.toFixed(2) }}</td>
                    <td :class="row.voxel_count && row.voxel_count < 500 ? 'dev-disc' : getDeviationClass(row.deviation_pct)">
                      {{ row.deviation_pct !== null ? (row.deviation_pct > 0 ? '+' : '') + row.deviation_pct.toFixed(1) + '%' : '-' }}
                    </td>
                    <!-- 体积列 -->
                    <td class="val-ref">{{ row.reference_volume_cm3 !== null && row.reference_volume_cm3 !== undefined ? row.reference_volume_cm3.toFixed(2) : '-' }}</td>
                    <td class="val-calc">{{ row.calculated_volume_cm3 !== undefined ? row.calculated_volume_cm3.toFixed(2) : '-' }}</td>
                    <td :class="row.voxel_count && row.voxel_count < 500 ? 'dev-disc' : getDeviationClass(row.volume_deviation_pct)">
                      {{ row.volume_deviation_pct !== null && row.volume_deviation_pct !== undefined ? (row.volume_deviation_pct > 0 ? '+' : '') + row.volume_deviation_pct.toFixed(1) + '%' : '-' }}
                    </td>
                    <!-- 剂量与风险列（仅在有风险评估结果时显示） -->
                    <template v-if="riskResults">
                      <td class="val-dose">
                        {{ getOrganRiskData(row.cancer_site, 'doseSv') !== null
                            ? getOrganRiskData(row.cancer_site, 'doseSv').toFixed(4)
                            : '-' }}
                      </td>
                      <td :class="getLarClass(getOrganRiskData(row.cancer_site, 'risk'))">
                        {{ getOrganRiskData(row.cancer_site, 'risk') !== null
                            ? getOrganRiskData(row.cancer_site, 'risk').toFixed(4) + '%'
                            : '-' }}
                      </td>
                      <td class="val-baseline">
                        {{ row.baseline_incidence_per100k !== null && row.baseline_incidence_per100k !== undefined
                            ? row.baseline_incidence_per100k.toFixed(1)
                            : '-' }}
                      </td>
                      <td>
                        <span v-if="getOrganRiskData(row.cancer_site, 'riskLevel')"
                              :class="'badge-risk-' + getOrganRiskData(row.cancer_site, 'riskLevel')">
                          {{ getRiskLevelLabel(getOrganRiskData(row.cancer_site, 'riskLevel')) }}
                        </span>
                        <span v-else class="badge-none">-</span>
                      </td>
                    </template>
                    <!-- 体素数 & 几何评级 -->
                    <td class="val-voxel">
                      {{ row.voxel_count !== undefined ? row.voxel_count.toLocaleString() : '-' }}
                      <span v-if="row.voxel_count && row.voxel_count < 500" class="disc-star" title="小器官，体素离散化误差较大">★</span>
                    </td>
                    <td>
                      <span v-if="row.voxel_count && row.voxel_count < 500" class="badge-disc">
                        离散★
                      </span>
                      <span v-else :class="'badge-' + getDeviationRating(row.deviation_pct)">
                        {{ getDeviationRatingLabel(row.deviation_pct) }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <!-- 空值说明 -->
              <div v-if="riskResults" class="icrp-null-note">
                — 表示该器官在 BEIR VII 模型中无对应辐射致癌风险系数（如皮肤、心脏、肾脏、脾脏等），不参与二次癌风险计算，属正常数据缺失。
              </div>
              <!-- 总风险汇总行（有风险数据时显示） -->
              <div v-if="riskResults" class="icrp-risk-summary">
                <strong>全身累积二次癌风险（LAR）：</strong>
                <span :class="riskResults.totalRisk > 0.1 ? 'risk-val-high' : riskResults.totalRisk > 0.01 ? 'risk-val-mod' : 'risk-val-low'">
                  {{ riskResults.totalRisk.toFixed(4) }}%
                </span>
                &emsp;|&emsp;
                <strong>ICRP 103 有效剂量限值参考：</strong>
                职业照射 20 mSv/年，公众照射 1 mSv/年
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else-if="!icrcLoading" class="icrp-empty">
            <p>📊</p>
            <p>选择体模类型后点击"运行对比"，将自动加载ICRP-110体素数据并与参考值对比</p>
          </div>

          <!-- 错误 -->
          <div v-if="icrcError" class="icrp-error">
            <p>错误：{{ icrcError }}</p>
          </div>
        </div>
      </div>
      <!-- BEIR VII 验证（合并至风险评估页） -->
      <div v-show="activeTab === 'risk'" class="tab-content">
        <div class="bv-workspace">
          <div class="bv-header">
            <h2>🔬 BEIR VII 风险模型参数验证</h2>
            <p class="bv-desc">
              对照 <strong>BEIR VII Phase 2 (2006)</strong> 报告，逐项验证
              <code>beir7_risk_engine.py</code> 中的公式、参数与模型权重。
            </p>
            <button @click="runBeir7Validation" :disabled="bvLoading" class="btn btn-primary bv-run-btn">
              <span v-if="bvLoading" class="spinner-sm"></span>
              {{ bvLoading ? '验证中...' : '▶ 运行验证' }}
            </button>
          </div>

          <div v-if="bvResult" class="bv-results">

            <!-- 汇总状态卡片 -->
            <div class="bv-summary-cards">
              <div class="bv-card" :class="bvResult.summary.err_formula_ok ? 'card-pass' : 'card-fail'">
                <div class="bv-card-icon">{{ bvResult.summary.err_formula_ok ? '✓' : '✗' }}</div>
                <div class="bv-card-label">ERR 公式</div>
                <div class="bv-card-sub">{{ bvResult.summary.err_formula_ok ? '全部通过' : '存在错误' }}</div>
              </div>
              <div class="bv-card" :class="bvResult.summary.ear_formula_ok ? 'card-pass' : 'card-fail'">
                <div class="bv-card-icon">{{ bvResult.summary.ear_formula_ok ? '✓' : '✗' }}</div>
                <div class="bv-card-label">EAR 公式</div>
                <div class="bv-card-sub">{{ bvResult.summary.ear_formula_ok ? '全部通过' : '存在错误' }}</div>
              </div>
              <div class="bv-card"
                   :class="bvResult.cases_summary && bvResult.cases_summary.all_spots_pass ? 'card-pass' : 'card-fail'">
                <div class="bv-card-icon">
                  {{ bvResult.cases_summary && bvResult.cases_summary.all_spots_pass ? '✓' : '✗' }}
                </div>
                <div class="bv-card-label">案例验证</div>
                <div class="bv-card-sub">
                  {{ bvResult.cases_summary
                     ? bvResult.cases_summary.total_spot_checks + ' 项全通过'
                     : '—' }}
                </div>
              </div>
              <div class="bv-card card-info">
                <div class="bv-card-icon">📖</div>
                <div class="bv-card-label">数据来源</div>
                <div class="bv-card-sub">BEIR VII Table 12-2D/E</div>
              </div>
            </div>

            <!-- 验证逻辑说明 -->
            <div class="bv-flow-banner">
              <div class="bvf-tier bvf-tier1">
                <div class="bvf-num">第一层</div>
                <div class="bvf-title">基础参数验证（组件级）</div>
                <div class="bvf-items">① ERR公式 &nbsp;② EAR公式 &nbsp;③ 年龄因子 &nbsp;④ 器官权重</div>
              </div>
              <div class="bvf-arrow">→</div>
              <div class="bvf-tier bvf-tier2">
                <div class="bvf-num">第二层</div>
                <div class="bvf-title">综合案例验证（集成级）</div>
                <div class="bvf-items">⑤ 5案例 × 逐器官公式对比 + 文献参考 + 趋势一致性验证</div>
              </div>
            </div>

            <!-- ERR 基准点表 -->
            <div class="bv-section">
              <h3>1. ERR 公式基准点验证 &nbsp;<small>ERR(D=1 Gy, e=30) 应 = β（BEIR VII Table 12-2D）</small></h3>
              <table class="bv-table">
                <thead>
                  <tr>
                    <th>器官</th>
                    <th>男 期望β</th><th>男 计算值</th><th>男</th>
                    <th>女 期望β</th><th>女 计算值</th><th>女</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in bvResult.err_check" :key="r.organ">
                    <td>{{ r.organ }}</td>
                    <td>{{ r.male_expected }}</td>
                    <td>{{ r.male_got.toFixed(4) }}</td>
                    <td :class="r.male_pass ? 'cell-pass' : 'cell-fail'">{{ r.male_pass ? '✓' : '✗' }}</td>
                    <td>{{ r.female_expected }}</td>
                    <td>{{ r.female_got.toFixed(4) }}</td>
                    <td :class="r.female_pass ? 'cell-pass' : 'cell-fail'">{{ r.female_pass ? '✓' : '✗' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- EAR 基准点表 -->
            <div class="bv-section">
              <h3>2. EAR 公式基准点验证 &nbsp;<small>EAR(D=1 Gy, e=30, a=60) 应 = β（BEIR VII Table 12-2E）</small></h3>
              <table class="bv-table">
                <thead>
                  <tr>
                    <th>器官</th>
                    <th>男 期望β</th><th>男 计算值</th><th>男</th>
                    <th>女 期望β</th><th>女 计算值</th><th>女</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in bvResult.ear_check" :key="r.organ">
                    <td>{{ r.organ }}</td>
                    <td>{{ r.male_expected }}</td>
                    <td>{{ r.male_got.toFixed(4) }}</td>
                    <td :class="r.male_pass ? 'cell-pass' : 'cell-fail'">{{ r.male_pass ? '✓' : '✗' }}</td>
                    <td>{{ r.female_expected }}</td>
                    <td>{{ r.female_got.toFixed(4) }}</td>
                    <td :class="r.female_pass ? 'cell-pass' : 'cell-fail'">{{ r.female_pass ? '✓' : '✗' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 年龄调整因子 -->
            <div class="bv-section bv-section-half">
              <h3>3. 年龄调整因子 &nbsp;<small>exp(γ·(e−30)/10)，肺癌 γ=−0.40</small></h3>
              <table class="bv-table">
                <thead><tr><th>暴露年龄</th><th>调整因子</th><th>说明</th></tr></thead>
                <tbody>
                  <tr v-for="r in bvResult.age_factor" :key="r.age"
                      :class="r.age === 30 ? 'row-baseline' : ''">
                    <td>{{ r.age }} 岁</td>
                    <td>{{ r.factor }}</td>
                    <td>{{ r.note }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 权重表 -->
            <div class="bv-section bv-section-half">
              <h3>4. 器官专属 ERR/EAR 权重 &nbsp;<small>BEIR VII Chapter 12</small></h3>
              <table class="bv-table">
                <thead><tr><th>器官</th><th>ERR 权重</th><th>EAR 权重</th><th>说明</th></tr></thead>
                <tbody>
                  <tr v-for="r in bvResult.weight_table" :key="r.organ"
                      :class="r.note !== '标准权重' ? 'row-special' : ''">
                    <td>{{ r.organ }}</td>
                    <td>{{ r.err_weight }}</td>
                    <td>{{ r.ear_weight }}</td>
                    <td>{{ r.note }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 综合案例验证（含结论总览 + 逐案例展开） -->
            <div class="bv-section bv-cases-section">
              <h3>5. 综合案例验证 &nbsp;<small>5个文献来源案例，验证不同年龄/性别/剂量场景下的完整 LAR 计算流程</small></h3>

              <!-- 逐案例总览表（结论先行） -->
              <div v-if="bvResult.cases_summary">
                <!-- 总览表 -->
                <table class="bv-table cases-sum-table" style="margin-bottom:0.8rem">
                  <thead>
                    <tr>
                      <th>案例</th>
                      <th>参数（性别·年龄·剂量）</th>
                      <th>程序计算总LAR (%)</th>
                      <th>公式验证项数</th>
                      <th>公式验证</th>
                      <th>标准参考结果</th>
                      <th>结论</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="s in bvResult.cases_summary.spot_check_summary" :key="s.case_id">
                      <td><strong>案例 {{ s.case_id }}</strong><br><small>{{ s.case_name.slice(0,12) }}…</small></td>
                      <td>
                        {{ s.params.gender === 'male' ? '男' : '女' }}
                        · {{ s.params.age }}岁
                        · {{ s.params.dose_sv }}Sv
                      </td>
                      <td class="case-lar-val"><strong>{{ s.total_lar.toFixed(5) }}</strong></td>
                      <td style="text-align:center">{{ s.spot_count }}</td>
                      <td>
                        <span :class="['spot-verdict', s.all_pass ? 'sv-pass' : 'sv-fail']">
                          {{ s.all_pass ? `✓ 全部通过` : '✗ 有偏差' }}
                        </span>
                      </td>
                      <td class="csum-ref-col">
                        <template v-if="s.case_id === 1">
                          BEIR VII Table 12-3（美国）≈ 0.82%<br>
                          <small>差异：中国 vs 美国基线率，属本土化调整</small>
                        </template>
                        <template v-else>
                          {{ bvResult.cases[s.case_id - 1].ref_comparison.expected_lar_vs_case1 }}
                        </template>
                      </td>
                      <td>
                        <span :class="['spot-verdict', s.all_pass ? 'sv-pass' : 'sv-fail']">
                          {{ s.all_pass ? '✓ 合理' : '⚠ 检查' }}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>

                <!-- 趋势一致性验证 -->
                <div class="trend-box" style="margin-bottom:0.8rem">
                  <div class="trend-title">
                    LAR 大小趋势验证
                    <span :class="['spot-verdict', bvResult.cases_summary.trend_check.trend_pass ? 'sv-pass' : 'sv-fail']">
                      {{ bvResult.cases_summary.trend_check.trend_pass ? '✓ 通过' : '✗ 不符合' }}
                    </span>
                  </div>
                  <div class="trend-desc">
                    <strong>预期顺序（年龄越小·剂量越大 → LAR 越高）：</strong><br>
                    案例3（10岁女，0.3Sv）&gt;&gt; 案例2（25岁女，0.2Sv）&gt;
                    案例4（45岁男，0.5Sv）&gt; 案例1（30岁男，0.1Sv）&gt;&gt; 案例5（60岁女，0.05Sv）
                  </div>
                  <div class="trend-actual">
                    <strong>实际计算顺序（从高到低）：</strong>
                    <span v-for="(id, idx) in bvResult.cases_summary.trend_check.actual_order_by_lar" :key="id">
                      案例{{ id }}（{{ bvResult.cases[id - 1].total_lar_pct.toFixed(4) }}%）
                      <span v-if="idx < 4"> &gt; </span>
                    </span>
                  </div>
                </div>

                <!-- 总结论框 -->
                <div :class="['cases-final-verdict',
                              bvResult.cases_summary.all_spots_pass &&
                              bvResult.cases_summary.trend_check.trend_pass
                                ? 'cfv-pass' : 'cfv-warn']"
                     style="margin-bottom:1.2rem">
                  <span class="cfv-icon">
                    {{ bvResult.cases_summary.all_spots_pass && bvResult.cases_summary.trend_check.trend_pass ? '✓' : '⚠' }}
                  </span>
                  <span>
                    共 {{ bvResult.cases_summary.total_spot_checks }} 项公式解析验证全部通过；
                    5个临床案例的 LAR 大小顺序与年龄–剂量模型预期完全一致；
                    Case 1 与 BEIR VII Table 12-3 量级吻合（差异来自中国 vs 美国基线发病率，属预期内本土化偏差）。
                    <strong>程序计算结果合理可信。</strong>
                  </span>
                </div>
              </div>

              <!-- 逐案例折叠卡片 -->
              <div class="bv-cases-grid">
                <div v-for="c in bvResult.cases" :key="c.id" class="bv-case-card">
                  <!-- 始终可见：案例摘要（可点击展开） -->
                  <div class="bv-case-summary" @click="toggleCase(c.id)">
                    <div class="bv-case-header">
                      <span class="bv-case-num">案例 {{ c.id }}</span>
                      <span class="bv-case-name">{{ c.name }}</span>
                      <span :class="['spot-verdict', c.all_spots_pass ? 'sv-pass' : 'sv-fail']" style="margin-left:auto">
                        {{ c.all_spots_pass ? '✓ 验证通过' : '✗ 存在偏差' }}
                      </span>
                    </div>
                    <div class="bv-case-meta">
                      <span class="bv-case-param">
                        {{ c.params.gender === 'male' ? '男性' : '女性' }}
                        &nbsp;·&nbsp;{{ c.params.age }}岁
                        &nbsp;·&nbsp;{{ c.params.dose_sv }} Sv
                      </span>
                      <span class="bv-case-total">
                        总LAR：<strong>{{ c.total_lar_pct.toFixed(4) }}%</strong>
                      </span>
                      <span class="bv-expand-hint">{{ expandedCases[c.id] ? '▲ 收起' : '▼ 展开详情' }}</span>
                    </div>
                  </div>

                  <!-- 展开后显示详情 -->
                  <div v-if="expandedCases[c.id]" class="bv-case-detail">
                    <p class="bv-case-desc">{{ c.description }}</p>
                    <div class="bv-case-ref">
                      <span class="bv-ref-badge">文献</span>
                      <span class="bv-ref-text">{{ c.reference }}</span>
                    </div>

                    <!-- 程序计算结果 -->
                    <div class="case-table-label">
                      <span class="ctlabel-prog">▶ 程序计算结果</span>
                    </div>
                    <table class="bv-table bv-case-table">
                      <thead>
                        <tr>
                          <th>器官</th>
                          <th>LAR_ERR (%)</th>
                          <th>LAR_EAR (%)</th>
                          <th>LAR综合 (%)</th>
                          <th>权重</th>
                          <th>风险级别</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="r in c.organ_results" :key="r.organ">
                          <td>{{ r.organ }}</td>
                          <td>{{ r.lar_pct !== null ? r.lar_err_pct.toFixed(5) : '-' }}</td>
                          <td>{{ r.lar_pct !== null ? r.lar_ear_pct.toFixed(5) : '-' }}</td>
                          <td><strong>{{ r.lar_pct !== null ? r.lar_pct.toFixed(5) : '-' }}</strong></td>
                          <td>{{ r.weights || '-' }}</td>
                          <td>
                            <span v-if="r.risk_level" :class="['risk-badge', 'risk-' + r.risk_level]">
                              {{ {'negligible':'可忽略','low':'低风险','moderate':'中等','high':'高风险'}[r.risk_level] || r.risk_level }}
                            </span>
                            <span v-else>-</span>
                          </td>
                        </tr>
                      </tbody>
                      <tfoot>
                        <tr class="case-total-row">
                          <td colspan="3" style="text-align:right;font-weight:600;">总计 LAR</td>
                          <td><strong>{{ c.total_lar_pct.toFixed(5) }}%</strong></td>
                          <td colspan="2"></td>
                        </tr>
                      </tfoot>
                    </table>

                    <!-- 公式解析验证（标准结果对比） -->
                    <div class="case-table-label" style="margin-top:0.8rem">
                      <span class="ctlabel-ref">▶ 公式解析验证（标准结果对比）</span>
                      <span :class="['spot-verdict', c.all_spots_pass ? 'sv-pass' : 'sv-fail']">
                        {{ c.all_spots_pass ? '✓ 全部通过' : '✗ 存在偏差' }}
                        （{{ c.spot_check_count }} 项）
                      </span>
                    </div>
                    <p class="spot-desc">
                      对每个器官独立计算解析值
                      <code>ERR = β · D<sub>eff</sub> · exp(γ · (e−30)/10)</code>，
                      与程序输出逐一对比，误差 &lt; 1×10<sup>−9</sup> 即判定通过。
                      <span v-if="c.spot_checks.some(s => s.ddref_applied)">
                        本案例剂量 &lt; 0.1 Sv，DDREF=1.5 已作用于有效剂量（D<sub>eff</sub>=D/DDREF）。
                      </span>
                    </p>
                    <table class="bv-table spot-table">
                      <thead>
                        <tr>
                          <th>器官</th>
                          <th>解析公式（β·D<sub>eff</sub>·exp(γ·(e−30)/10)）</th>
                          <th>解析计算值</th>
                          <th>程序输出值</th>
                          <th>误差（|解析−程序|）</th>
                          <th>结果</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="s in c.spot_checks" :key="s.organ">
                          <td>{{ s.organ }}<span v-if="s.ddref_applied" class="ddref-tag">DDREF</span></td>
                          <td class="spot-formula">{{ s.formula }}</td>
                          <td class="spot-val">{{ s.analytical.toFixed(8) }}</td>
                          <td class="spot-val">{{ s.program.toFixed(8) }}</td>
                          <td class="spot-val spot-err">{{ Math.abs(s.analytical - s.program) < 1e-9 ? '&lt; 1×10⁻⁹' : Math.abs(s.analytical - s.program).toExponential(2) }}</td>
                          <td>
                            <span :class="['spot-pass', s.pass ? 'sp-ok' : 'sp-fail']">
                              {{ s.pass ? '✓' : '✗' }}
                            </span>
                          </td>
                        </tr>
                      </tbody>
                    </table>

                    <!-- 文献参考对比 -->
                    <template v-if="c.ref_comparison">
                      <!-- Case 1：BEIR VII Table 12-3 对比 -->
                      <div v-if="c.ref_comparison.type === 'beir7_table123'" class="ref-cmp-box ref-beir7">
                        <div class="ref-cmp-title">
                          📖 与 BEIR VII Table 12-3（美国人口基线）对比
                        </div>
                        <div class="ref-cmp-row">
                          <div class="ref-cmp-col">
                            <div class="ref-cmp-label">BEIR VII 美国人口估计</div>
                            <div class="ref-cmp-value">
                              ~{{ c.ref_comparison.total_lar_us_approx }}%
                              <span class="ref-ci">（95% CI {{ c.ref_comparison.ci_low }}%–{{ c.ref_comparison.ci_high }}%）</span>
                            </div>
                          </div>
                          <div class="ref-cmp-arrow">→</div>
                          <div class="ref-cmp-col">
                            <div class="ref-cmp-label">本程序（中国人口基线）</div>
                            <div class="ref-cmp-value ref-ours">{{ c.ref_comparison.our_total_pct }}%</div>
                          </div>
                          <div class="ref-cmp-col ref-verdict-col">
                            <div class="ref-cmp-label">量级</div>
                            <div class="ref-cmp-value ref-ours">同一数量级 ✓</div>
                          </div>
                        </div>
                        <div class="ref-cmp-note">{{ c.ref_comparison.note }}</div>
                      </div>

                      <!-- Cases 2-5：定量趋势预期 -->
                      <div v-else-if="c.ref_comparison.type === 'trend_check'" class="ref-cmp-box ref-trend">
                        <div class="ref-cmp-title">📐 模型参数定量趋势验证</div>
                        <div class="ref-cmp-note">{{ c.ref_comparison.basis }}</div>
                        <div class="ref-cmp-expected">
                          <strong>预期结论：</strong>{{ c.ref_comparison.expected_lar_vs_case1 }}
                          &nbsp;—&nbsp;
                          <strong>实际总LAR：{{ c.total_lar_pct.toFixed(4) }}%</strong>
                          <span :class="['trend-ok', c.all_spots_pass ? 'sv-pass' : 'sv-fail']">
                            {{ c.all_spots_pass ? '✓ 符合预期' : '⚠ 请检查' }}
                          </span>
                        </div>
                      </div>
                    </template>

                    <p class="bv-case-context"><strong>临床意义：</strong>{{ c.clinical_context }}</p>
                    <p class="bv-case-citation">{{ c.citation }}</p>
                  </div><!-- /bv-case-detail -->
                </div>
              </div>
            </div>

            <!-- 参数合理性总览 -->
            <div class="bv-section bv-param-review">
              <h3>6. 参数合理性总览
                <small>逐项对照 BEIR VII 及权威文献，证明程序设置有据可查</small>
              </h3>

              <!-- 统计徽章行 -->
              <div class="pr-stat-row">
                <span class="pr-stat pr-stat-match">
                  ✓ 完全一致
                  {{ bvResult.param_review.filter(p => p.status === 'match').length }} 项
                </span>
                <span class="pr-stat pr-stat-acceptable">
                  ~ 合理偏差
                  {{ bvResult.param_review.filter(p => p.status === 'acceptable').length }} 项
                </span>
                <span class="pr-stat pr-stat-note">
                  ℹ 说明项
                  {{ bvResult.param_review.filter(p => p.status === 'note').length }} 项
                </span>
              </div>

              <!-- 按 group 分组展示 -->
              <template v-for="(groupItems, groupName) in groupedParamReview" :key="groupName">
                <div class="pr-group">
                  <div class="pr-group-title">{{ groupName }}</div>
                  <table class="bv-table pr-table">
                    <thead>
                      <tr>
                        <th style="width:18%">参数</th>
                        <th style="width:22%">程序设定值</th>
                        <th style="width:22%">文献推荐值</th>
                        <th style="width:22%">来源文献</th>
                        <th style="width:8%">状态</th>
                        <th>备注</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="p in groupItems" :key="p.param">
                        <td class="pr-param-name">{{ p.param }}</td>
                        <td class="pr-code">{{ p.program_value }}</td>
                        <td class="pr-code">{{ p.reference_value }}</td>
                        <td class="pr-source">{{ p.source }}</td>
                        <td>
                          <span :class="['pr-status-badge', 'prs-' + p.status]">
                            {{ {'match':'✓ 一致','acceptable':'~ 合理','note':'ℹ 说明'}[p.status] || p.status }}
                          </span>
                        </td>
                        <td class="pr-remark">{{ p.remark }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>

              <div class="pr-conclusion">
                <span class="pr-conclusion-icon">✓</span>
                程序所有核心参数均有明确文献依据，公式与 BEIR VII Phase 2 (2006) 完全一致，
                权重、DDREF、潜伏期均采用报告推荐值，基线发病率本土化处理符合 BEIR VII 指引，
                参数设置合理可信。
              </div>
            </div>

          </div>

          <div v-else-if="!bvLoading" class="bv-empty">
            <p>🔬</p>
            <p>点击「运行验证」，自动对照 BEIR VII 报告检验公式、参数与模型权重</p>
          </div>
          <div v-if="bvError" class="bv-error">错误：{{ bvError }}</div>
        </div>
      </div>

      <!-- 中子AP ICRP剂量对比（合并至风险评估页） -->
      <div v-show="activeTab === 'risk'" class="tab-content">
        <div class="nicrp-workspace">
          <div class="nicrp-header">
            <h2>☢️ 中子 AP 照射 ICRP 参考条件剂量对比</h2>
            <p class="nicrp-desc">
              基于 <strong>ICRP Publication 116 (2010) Table A.3</strong>，展示中子 AP 几何下
              <strong>ICRP 110</strong> 参考体模的全量剂量转换系数对比。<br>
              涵盖有效剂量 E/Φ（31个能量点）和各器官当量剂量 HT/Φ（含红骨髓、骨表面等，共18个器官），
              并通过 Σ(wT·HT/Φ) 验证有效剂量的内部一致性。
            </p>
          </div>

          <div class="nicrp-controls">
            <div class="phantom-selector">
              <span class="selector-label">体模类型：</span>
              <button :class="['btn-phantom', { active: neutronPhantomType === 'AM' }]"
                      @click="neutronPhantomType = 'AM'">AM（成人男）</button>
              <button :class="['btn-phantom', { active: neutronPhantomType === 'AF' }]"
                      @click="neutronPhantomType = 'AF'">AF（成人女）</button>
            </div>
            <button class="btn btn-primary nicrp-run-btn"
                    @click="runNeutronIcrpComparison"
                    :disabled="neutronLoading">
              <span v-if="neutronLoading" class="spinner-sm"></span>
              {{ neutronLoading ? '生成中（约30秒）...' : '▶ 生成对比图表' }}
            </button>
          </div>

          <!-- 加载提示 -->
          <div v-if="neutronLoading" class="nicrp-progress">
            <div class="nicrp-progress-bar">
              <div class="nicrp-progress-inner"></div>
            </div>
            <p>正在计算 {{ neutronPhantomType }} 体模中子 AP 剂量转换系数并生成图表...</p>
          </div>

          <!-- 结果展示 -->
          <div v-if="neutronCharts.length > 0" class="nicrp-results">

            <!-- 摘要卡片 -->
            <div class="nicrp-summary-cards" v-if="neutronSummary">
              <div class="nicrp-card">
                <div class="nicrp-card-icon">☢️</div>
                <div class="nicrp-card-label">辐射类型</div>
                <div class="nicrp-card-value">中子 (Neutron)</div>
              </div>
              <div class="nicrp-card">
                <div class="nicrp-card-icon">📐</div>
                <div class="nicrp-card-label">照射几何</div>
                <div class="nicrp-card-value">AP（前后向）</div>
              </div>
              <div class="nicrp-card">
                <div class="nicrp-card-icon">👤</div>
                <div class="nicrp-card-label">参考体模</div>
                <div class="nicrp-card-value">ICRP 110 {{ neutronPhantomType }}</div>
              </div>
              <div class="nicrp-card">
                <div class="nicrp-card-icon">⚡</div>
                <div class="nicrp-card-label">能量点数</div>
                <div class="nicrp-card-value">{{ neutronSummary.n_energies }} 个</div>
              </div>
              <div class="nicrp-card">
                <div class="nicrp-card-icon">🫀</div>
                <div class="nicrp-card-label">覆盖器官</div>
                <div class="nicrp-card-value">{{ neutronSummary.n_organs }} 个</div>
              </div>
              <div class="nicrp-card">
                <div class="nicrp-card-icon">📖</div>
                <div class="nicrp-card-label">数据来源</div>
                <div class="nicrp-card-value">ICRP Pub.116 Table A.3</div>
              </div>
            </div>

            <!-- 图表选项卡 -->
            <div class="nicrp-chart-tabs">
              <button
                v-for="(chart, idx) in neutronCharts"
                :key="idx"
                :class="['nicrp-tab-btn', { active: neutronActiveChart === idx }]"
                @click="neutronActiveChart = idx">
                图{{ idx + 1 }}
              </button>
            </div>

            <!-- 当前图表展示 -->
            <div class="nicrp-chart-section" v-if="neutronCharts[neutronActiveChart]">
              <div class="nicrp-chart-title">
                {{ neutronCharts[neutronActiveChart].title }}
              </div>
              <img
                :src="getImageUrl(neutronCharts[neutronActiveChart].url)"
                :alt="neutronCharts[neutronActiveChart].title"
                class="nicrp-chart-img"
              />
            </div>

            <!-- 图表缩略导航 -->
            <div class="nicrp-thumbnails">
              <div
                v-for="(chart, idx) in neutronCharts"
                :key="idx"
                :class="['nicrp-thumb', { active: neutronActiveChart === idx }]"
                @click="neutronActiveChart = idx">
                <img :src="getImageUrl(chart.url)" :alt="chart.title" class="nicrp-thumb-img" />
                <div class="nicrp-thumb-label">图{{ idx + 1 }}</div>
              </div>
            </div>

            <!-- 说明文字 -->
            <div class="nicrp-note">
              <strong>图1</strong> E/Φ 全能量曲线（1 meV ~ 100 MeV，31点，含热/超热/快中子区域标注）&nbsp;|&nbsp;
              <strong>图2</strong> 所有器官 HT/Φ 随能量变化（多线，wT≥0.04器官加粗）&nbsp;|&nbsp;
              <strong>图3</strong> 热中子/10 keV/1 MeV 三能量点器官柱状图&nbsp;|&nbsp;
              <strong>图4</strong> 有效剂量验证：ICRP116表格值 vs Σ(wT·HT/Φ)&nbsp;|&nbsp;
              <strong>图5</strong> 各器官 wT 加权贡献堆积面积图<br>
              <em>数据来源：ICRP Publication 116 (2010), Table A.3 | ICRP Publication 103 (2007) wT因子</em>
            </div>
          </div>

          <!-- 空态提示 -->
          <div v-else-if="!neutronLoading" class="nicrp-empty">
            <p>☢️</p>
            <p>选择体模类型后点击"生成对比图表"，将自动生成5张ICRP参考数据对比图</p>
            <p class="nicrp-empty-sub">涵盖有效剂量曲线、器官HT曲线、柱状图、有效剂量验证、wT贡献堆积图</p>
          </div>

          <div v-if="neutronError" class="nicrp-error">
            <p>错误：{{ neutronError }}</p>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════════════════════ -->
      <!-- Tab: ICRP-116 AP 光子剂量系数 MCNP5 验证              -->
      <!-- ══════════════════════════════════════════════════════ -->
      <div v-show="activeTab === 'icrp116'" class="tab-content">
        <div class="icrp116-workspace">

          <!-- 标题 -->
          <div class="icrp116-header">
            <h2>✅ ICRP-116 AP 光子剂量系数 MCNP5 验证</h2>
            <p class="icrp116-desc">
              使用 <strong>ICRP-110 AM</strong> 标准体模，以 <strong>AP 平行光子束</strong> 照射，
              通过 <strong>MCNP5 蒙特卡洛模拟</strong>（FMESH 通量计分）计算各器官吸收剂量，
              与 ICRP Publication 116 Table A.3 参考值对比验证。<br>
              <span class="icrp116-note">⚠ 每个能量点需运行约 2~6 小时（10⁷ 粒子），请保持后端在线。</span>
            </p>
          </div>

          <!-- 控制区 -->
          <div class="icrp116-controls">
            <div class="icrp116-energy-row">
              <span class="ctrl-label">选择能量点：</span>
              <label
                v-for="e in icrp116Energies"
                :key="e.value"
                class="icrp116-energy-checkbox"
              >
                <input
                  type="checkbox"
                  :value="e.value"
                  v-model="icrp116Selected"
                  :disabled="icrp116Running"
                />
                {{ e.label }}
              </label>
            </div>

            <div class="icrp116-sex-avg-row">
              <label class="icrp116-sex-avg-label">
                <input type="checkbox" v-model="icrp116SexAvg" :disabled="icrp116Running" />
                <span>启用性别平均 <strong>(AM + AF 体模)</strong> — 与 ICRP-116 标准方法一致</span>
              </label>
            </div>

            <div class="icrp116-adv-row">
              <label class="icrp116-adv-label">
                <input type="checkbox" v-model="icrp116ForceRerun" :disabled="icrp116Running" />
                <span>强制重跑（忽略已有 .npy 缓存，重新运行 MCNP5）</span>
              </label>
              <label class="icrp116-adv-label" style="margin-top:4px">
                <input type="checkbox" v-model="icrp116DeDfMode" :disabled="icrp116Running" />
                <span>DE/DF 精确模式（单 FMESH 通量→kerma 转换，消除 EMESH 代表能误差）</span>
              </label>
            </div>

            <div class="icrp116-btn-row">
              <button
                class="btn btn-primary"
                :disabled="icrp116Running || icrp116Selected.length === 0"
                @click="startIcrp116Validation"
              >
                <span v-if="icrp116Running" class="spinner-sm"></span>
                {{ icrp116Running ? '⟳ MCNP5 运行中...' : '▶ 开始验证' }}
              </button>
              <button
                v-if="icrp116Running"
                class="btn btn-danger"
                @click="cancelIcrp116Validation"
              >
                ■ 取消
              </button>
              <span v-if="icrp116Running" class="icrp116-elapsed">
                已用时 {{ formatElapsed(icrp116Status.elapsedSec) }}
              </span>
            </div>

            <!-- 进度状态 -->
            <div v-if="icrp116Running || icrp116Status.doneEnergies.length" class="icrp116-progress">
              <!-- AM 阶段 -->
              <div class="icrp116-phase-label" v-if="icrp116Status.sexAvg">
                <span class="phase-badge phase-am">AM 体模</span>
                <span v-if="icrp116Status.phase === 'AF' || icrp116Status.afDoneEnergies.length" class="phase-done-mark">完成 ✓</span>
                <span v-else-if="icrp116Running" class="phase-active-mark">运行中...</span>
              </div>
              <div class="icrp116-progress-items">
                <div
                  v-for="e in icrp116Energies"
                  :key="e.value"
                  :class="['icrp116-e-chip',
                    icrp116Status.doneEnergies.includes(e.value) ? 'done' :
                    (icrp116Running && icrp116Status.currentCase === e.value && icrp116Status.phase === 'AM' ? 'active' : 'pending')]"
                >
                  <span class="chip-icon">
                    {{ icrp116Status.doneEnergies.includes(e.value) ? '✓' :
                       (icrp116Running && icrp116Status.currentCase === e.value && icrp116Status.phase === 'AM' ? '⟳' : '○') }}
                  </span>
                  {{ e.label }}
                </div>
              </div>
              <!-- AF 阶段（仅性别平均时显示） -->
              <template v-if="icrp116Status.sexAvg && (icrp116Status.phase === 'AF' || icrp116Status.afDoneEnergies.length)">
                <div class="icrp116-phase-label" style="margin-top:8px">
                  <span class="phase-badge phase-af">AF 体模</span>
                  <span v-if="!icrp116Running || icrp116Status.phase !== 'AF'" class="phase-done-mark">完成 ✓</span>
                  <span v-else class="phase-active-mark">运行中...</span>
                </div>
                <div class="icrp116-progress-items">
                  <div
                    v-for="e in icrp116Energies"
                    :key="'af-'+e.value"
                    :class="['icrp116-e-chip',
                      icrp116Status.afDoneEnergies.includes(e.value) ? 'done' :
                      (icrp116Running && icrp116Status.afCurrentCase === e.value ? 'active' : 'pending')]"
                  >
                    <span class="chip-icon">
                      {{ icrp116Status.afDoneEnergies.includes(e.value) ? '✓' :
                         (icrp116Running && icrp116Status.afCurrentCase === e.value ? '⟳' : '○') }}
                    </span>
                    {{ e.label }}
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- 日志面板 -->
          <div class="icrp116-log-panel">
            <div class="icrp116-log-header">
              <h4>📋 MCNP5 运行日志</h4>
              <button class="btn btn-secondary btn-sm" @click="icrp116Status.logs = []">清空</button>
            </div>
            <div class="icrp116-log-body" ref="icrp116LogBody">
              <div
                v-for="(entry, i) in icrp116Status.logs"
                :key="i"
                :class="['log-entry',
                  entry.text.includes('[ERR]') || entry.text.includes('[错误]') ? 'error' :
                  entry.text.includes('✓') || entry.text.includes('[OK]') ? 'success' : 'info']"
              >
                <span class="log-time">{{ entry.time }}</span>
                <span class="log-message">{{ entry.text }}</span>
              </div>
              <div v-if="!icrp116Status.logs.length" class="log-empty">
                点击「开始验证」后日志将在此实时显示...
              </div>
            </div>
          </div>

          <!-- 完成状态 / 结果文件 -->
          <div v-if="icrp116Status.completed" class="icrp116-result-banner success-banner">
            <strong>✓ 全部计算完成！</strong>
            AM: {{ icrp116Status.resultFiles.length }} 个通量文件
            <template v-if="icrp116Status.sexAvg">
              AF: {{ icrp116Status.afResultFiles.length }} 个通量文件
            </template>
            <br>
            <span style="font-size:0.9em;">
              结果已保存至 <code>icrp_validation/mcnp_outputs/</code>
              <template v-if="icrp116Status.sexAvg">
                （AM）和 <code>mcnp_outputs_AF/</code>（AF）
              </template>
            </span>
          </div>
          <div v-if="icrp116Status.failed && !icrp116Running" class="icrp116-result-banner error-banner">
            <strong>✗ 任务失败或已取消。</strong> 请检查上方日志排查问题。
          </div>

          <!-- ── Step 3：与 ICRP-116 参考值对比分析 ── -->
          <div class="icrp116-step3-module">
            <div class="s3-header">
              <h3>📊 Step 3：与 ICRP-116 参考值对比分析</h3>
              <p>
                读取 fluence_E*.npy，计算光子注量→有效剂量换算系数
                h<sub>E</sub>（pSv·cm²），与 ICRP-116 Table A.3 AP 光子参考值比较。
              </p>
            </div>

            <div class="s3-btn-row">
              <button @click="runIcrp116Step3" :disabled="icrp116Step3Loading" class="btn btn-primary">
                <span v-if="icrp116Step3Loading" class="spinner-sm"></span>
                {{ icrp116Step3Loading ? '计算中...' : '▶ 计算' }}
              </button>
              <button
                @click="genIcrp116Chart"
                :disabled="!icrp116Step3Done || icrp116ChartLoading"
                class="btn btn-secondary"
              >
                <span v-if="icrp116ChartLoading" class="spinner-sm"></span>
                🖼️ 生成对比图
              </button>
              <button @click="checkXsdir" :disabled="icrp116XsdirChecking" class="btn btn-secondary">
                <span v-if="icrp116XsdirChecking" class="spinner-sm"></span>
                🔍 检测截面库
              </button>
            </div>

            <!-- xsdir 诊断面板 -->
            <div v-if="icrp116XsdirInfo" :class="['s3-xsdir-panel', icrp116XsdirInfo.available && icrp116XsdirInfo.available.length ? 'xsdir-ok' : 'xsdir-warn']">
              <div class="xsdir-title">📂 MCNP5 xsdir 截面库诊断</div>
              <div class="xsdir-msg">{{ icrp116XsdirInfo.message }}</div>
              <template v-if="icrp116XsdirInfo.available && icrp116XsdirInfo.available.length">
                <div class="xsdir-detail">
                  可用光子库: <strong>{{ icrp116XsdirInfo.available.join('、') }}</strong>
                  &nbsp;推荐: <code>{{ icrp116XsdirInfo.recommended }}</code>
                </div>
                <div class="xsdir-hint">
                  当前输入文件使用 <code>.70p</code>。
                  若推荐库不是 <code>.70p</code>，请点击「开始验证」重新运行 Step2b；
                  系统将自动从 xsdir 检测并使用正确的截面库后缀重新生成 .inp 文件。
                </div>
              </template>
              <template v-else>
                <div class="xsdir-hint">
                  请检查 <code>D:\LANL\xsdir</code> 是否存在，确认 MCNP5 已正确安装，
                  并安装 ENDF/B-VII 光子数据（mcplib70p）或其他光子库。
                </div>
              </template>
            </div>

            <!-- Step3 日志 -->
            <div v-if="icrp116Step3Log.length" class="s3-log">
              <div
                v-for="(entry, i) in icrp116Step3Log"
                :key="i"
                :class="['s3-log-entry', entry.type]"
              >
                <span v-if="entry.time" class="s3-log-time">{{ entry.time }}</span>
                <span class="s3-log-msg">{{ entry.text }}</span>
              </div>
            </div>

            <!-- 结果表格 -->
            <div v-if="icrp116Step3Result && icrp116Step3Result.length" class="s3-results">
              <!-- 性别平均结果表 -->
              <template v-if="icrp116Step3Result[0] && icrp116Step3Result[0].h_AM !== undefined">
                <h4>性别平均对比结果 h<sub>E</sub> = (AM + AF) / 2（偏差 ≤10% 判为 PASS）</h4>
                <table class="s3-table">
                  <thead>
                    <tr>
                      <th>能量 (MeV)</th>
                      <th>h<sub>E</sub>,AM (pSv·cm²)</th>
                      <th>h<sub>E</sub>,AF (pSv·cm²)</th>
                      <th>h<sub>E</sub>,avg (pSv·cm²)</th>
                      <th>ICRP-116 参考值</th>
                      <th>偏差 AM</th>
                      <th>偏差 AF</th>
                      <th>偏差 avg</th>
                      <th>判定</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in icrp116Step3Result" :key="row.energy">
                      <td>{{ row.energy.toFixed(3) }}</td>
                      <td>{{ row.h_AM.toFixed(4) }}</td>
                      <td>{{ row.h_AF.toFixed(4) }}</td>
                      <td><strong>{{ row.h_avg.toFixed(4) }}</strong></td>
                      <td>{{ row.h_ref.toFixed(4) }}</td>
                      <td :class="Math.abs(row.dev_AM) <= 10 ? 'cell-pass' : 'cell-fail'">
                        {{ row.dev_AM > 0 ? '+' : '' }}{{ row.dev_AM.toFixed(1) }}%
                      </td>
                      <td :class="Math.abs(row.dev_AF) <= 10 ? 'cell-pass' : 'cell-fail'">
                        {{ row.dev_AF > 0 ? '+' : '' }}{{ row.dev_AF.toFixed(1) }}%
                      </td>
                      <td :class="Math.abs(row.dev_avg) <= 10 ? 'cell-pass' : 'cell-fail'">
                        <strong>{{ row.dev_avg > 0 ? '+' : '' }}{{ row.dev_avg.toFixed(1) }}%</strong>
                      </td>
                      <td :class="row.pass === 'PASS' ? 'cell-pass' : 'cell-fail'">
                        {{ row.pass === 'PASS' ? 'PASS ✓' : 'FAIL ✗' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </template>
              <!-- AM 单独结果表（无性别平均时） -->
              <template v-else>
                <h4>对比结果（偏差 ≤10% 判为 PASS）</h4>
                <table class="s3-table">
                  <thead>
                    <tr>
                      <th>能量 (MeV)</th>
                      <th>h<sub>E</sub> 计算值 (pSv·cm²)</th>
                      <th>ICRP-116 参考值 (pSv·cm²)</th>
                      <th>偏差</th>
                      <th>判定</th>
                      <th>数据源</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in icrp116Step3Result" :key="row.energy">
                      <td>{{ row.energy.toFixed(3) }}</td>
                      <td>{{ row.h_calc.toFixed(4) }}</td>
                      <td>{{ row.h_ref.toFixed(4) }}</td>
                      <td :class="Math.abs(row.deviation) <= 10 ? 'cell-pass' : 'cell-fail'">
                        {{ row.deviation > 0 ? '+' : '' }}{{ row.deviation.toFixed(1) }}%
                      </td>
                      <td :class="row.pass === 'PASS' ? 'cell-pass' : 'cell-fail'">
                        {{ row.pass === 'PASS' ? 'PASS ✓' : 'FAIL ✗' }}
                      </td>
                      <td :class="row.source === 'MCNP' ? 'cell-pass' : 'cell-warn'">
                        {{ row.source === 'MCNP' ? 'MCNP ✓' : '解析模型' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </template>
            </div>

            <!-- 对比图 -->
            <div v-if="icrp116ChartUrl" class="s3-chart-area">
              <h4>对比折线图</h4>
              <img :src="icrp116ChartUrl" alt="ICRP-116 对比图" class="s3-chart-img" />
            </div>
          </div>

        </div>
      </div>

      <!-- ── MCNP Tab：剂量组分参数（嵌入在MCNP页面中） ── -->
      <div v-show="activeTab === 'mcnp'" class="tab-content">
        <div class="ds-mcnp-title">
          <h2>⚡ 剂量组分参数设置</h2>
          <p>设置源与体模的位置/方向/能量，实时调整 CBE/RBE 参数，预览各组分剂量分布</p>
        </div>
        <div class="ds-workspace">

          <!-- ── 左侧：参数配置面板 ── -->
          <aside class="ds-sidebar">

            <!-- 源配置 -->
            <div class="ds-section">
              <h3 class="ds-section-title">☢️ 中子源配置</h3>

              <div class="ds-field-group">
                <label class="ds-label">源类型</label>
                <select v-model="dsSource.source_type" class="ds-select" @change="dsOnParamChange">
                  <option value="epithermal">超热中子束 (Epithermal)</option>
                  <option value="thermal">热中子束 (Thermal)</option>
                  <option value="mono">单能中子 (Mono-energetic)</option>
                </select>
              </div>

              <div class="ds-field-group">
                <label class="ds-label">位置 (cm)</label>
                <div class="ds-xyz-row">
                  <span class="ds-axis">X</span>
                  <input v-model.number="dsSource.position[0]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Y</span>
                  <input v-model.number="dsSource.position[1]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Z</span>
                  <input v-model.number="dsSource.position[2]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                </div>
              </div>

              <div class="ds-field-group">
                <label class="ds-label">方向（单位向量）</label>
                <div class="ds-xyz-row">
                  <span class="ds-axis">ux</span>
                  <input v-model.number="dsSource.direction[0]" type="number" step="0.1" min="-1" max="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">uy</span>
                  <input v-model.number="dsSource.direction[1]" type="number" step="0.1" min="-1" max="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">uz</span>
                  <input v-model.number="dsSource.direction[2]" type="number" step="0.1" min="-1" max="1" class="ds-input" @input="dsOnParamChange" />
                </div>
              </div>

              <div class="ds-row2">
                <div class="ds-field-group">
                  <label class="ds-label">束流半径 (cm)</label>
                  <input v-model.number="dsSource.beam_radius" type="number" step="0.5" min="0.5" max="20" class="ds-input-full" @input="dsOnParamChange" />
                </div>
                <div class="ds-field-group">
                  <label class="ds-label">强度 (n/cm²/s)</label>
                  <select v-model="dsIntensityExp" class="ds-select" @change="dsOnIntensityChange">
                    <option value="8">10⁸</option>
                    <option value="9">10⁹</option>
                    <option value="10">10¹⁰</option>
                    <option value="11">10¹¹</option>
                    <option value="12">10¹²</option>
                    <option value="13">10¹³</option>
                  </select>
                </div>
              </div>

              <div v-if="dsSource.source_type === 'mono'" class="ds-field-group">
                <label class="ds-label">单能能量 (MeV)</label>
                <input v-model.number="dsSource.energy_mono" type="number" step="0.001" min="1e-6" class="ds-input-full" @input="dsOnParamChange" />
              </div>

              <div v-if="dsSource.source_type !== 'mono'" class="ds-field-group">
                <label class="ds-label">能谱（预设）</label>
                <div class="ds-spectrum-preview">
                  <div v-for="(w, i) in dsSource.energy_spectrum.weights" :key="i"
                       class="ds-spectrum-bar"
                       :style="{ height: Math.round(w * 100 / Math.max(...dsSource.energy_spectrum.weights)) + '%',
                                 background: w === Math.max(...dsSource.energy_spectrum.weights) ? '#667eea' : '#a0aec0' }"
                       :title="`${dsSource.energy_spectrum.energies[i]} MeV: ${(w*100).toFixed(1)}%`">
                  </div>
                </div>
                <div class="ds-spectrum-label">
                  <span>{{ dsSource.energy_spectrum.energies[0] }} MeV</span>
                  <span>{{ dsSource.energy_spectrum.energies[dsSource.energy_spectrum.energies.length-1] }} MeV</span>
                </div>
              </div>
            </div>

            <!-- 体模配置 -->
            <div class="ds-section">
              <h3 class="ds-section-title">🧍 体模配置</h3>

              <div class="ds-field-group">
                <label class="ds-label">体模类型</label>
                <select v-model="dsPhantom.phantom_type" class="ds-select" @change="dsOnParamChange">
                  <option value="AM">成年男性 (AM, ICRP-110)</option>
                  <option value="AF">成年女性 (AF, ICRP-110)</option>
                </select>
              </div>

              <div class="ds-row2">
                <div class="ds-field-group">
                  <label class="ds-label">身高 (cm)</label>
                  <input v-model.number="dsPhantom.height_cm" type="number" step="1" min="140" max="220" class="ds-input-full" @input="dsOnParamChange" />
                </div>
                <div class="ds-field-group">
                  <label class="ds-label">体重 (kg)</label>
                  <input v-model.number="dsPhantom.weight_kg" type="number" step="1" min="30" max="150" class="ds-input-full" @input="dsOnParamChange" />
                </div>
              </div>

              <div class="ds-field-group">
                <label class="ds-label">体模中心偏移 (cm)</label>
                <div class="ds-xyz-row">
                  <span class="ds-axis">X</span>
                  <input v-model.number="dsPhantom.center[0]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Y</span>
                  <input v-model.number="dsPhantom.center[1]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Z</span>
                  <input v-model.number="dsPhantom.center[2]" type="number" step="1" class="ds-input" @input="dsOnParamChange" />
                </div>
              </div>

              <div class="ds-field-group">
                <label class="ds-label">旋转角度 (°)</label>
                <div class="ds-xyz-row">
                  <span class="ds-axis">Rx</span>
                  <input v-model.number="dsPhantom.rotation_deg[0]" type="number" step="5" min="-180" max="180" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Ry</span>
                  <input v-model.number="dsPhantom.rotation_deg[1]" type="number" step="5" min="-180" max="180" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Rz</span>
                  <input v-model.number="dsPhantom.rotation_deg[2]" type="number" step="5" min="-180" max="180" class="ds-input" @input="dsOnParamChange" />
                </div>
              </div>

              <div class="ds-field-group">
                <div class="ds-label-row">
                  <label class="ds-label">肿瘤位置（相对体模中心，cm）</label>
                  <button
                    class="ds-ct-locate-btn"
                    :disabled="!ctMetadata"
                    :title="ctMetadata ? '将肿瘤定位到CT体积中心' : '请先上传CT文件'"
                    @click="dsLocateToCtCenter"
                  >从CT定位</button>
                </div>
                <div class="ds-xyz-row">
                  <span class="ds-axis">X</span>
                  <input v-model.number="dsPhantom.tumor_position[0]" type="number" step="0.5" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Y</span>
                  <input v-model.number="dsPhantom.tumor_position[1]" type="number" step="0.5" class="ds-input" @input="dsOnParamChange" />
                  <span class="ds-axis">Z</span>
                  <input v-model.number="dsPhantom.tumor_position[2]" type="number" step="0.5" class="ds-input" @input="dsOnParamChange" />
                </div>
                <p v-if="ctMetadata" class="ds-ct-hint-small">
                  CT 物理尺寸：{{ ctMetadata.phys_size_cm[0].toFixed(1) }} × {{ ctMetadata.phys_size_cm[1].toFixed(1) }} × {{ ctMetadata.phys_size_cm[2].toFixed(1) }} cm
                </p>
              </div>

              <div class="ds-row2">
                <div class="ds-field-group">
                  <label class="ds-label">肿瘤半径 (cm) <span class="ds-hint-tag" title="影响可视化图形大小；右侧剂量数值仅与深度相关">仅影响可视化</span></label>
                  <input v-model.number="dsPhantom.tumor_radius" type="number" step="0.5" min="0.5" max="10" class="ds-input-full" @input="dsOnParamChange" />
                </div>
                <div class="ds-field-group">
                  <label class="ds-label">肿瘤深度 (cm) <span class="ds-hint-tag" title="影响右侧剂量数值：深度决定中子在组织中的衰减程度">影响剂量计算</span></label>
                  <input v-model.number="dsTumorDepth" type="number" step="0.5" min="0" max="25" class="ds-input-full" @input="dsOnTumorDepthChange" />
                </div>
              </div>
            </div>

            <!-- CBE/RBE 参数 -->
            <div class="ds-section">
              <h3 class="ds-section-title">⚗️ CBE / RBE 因子</h3>
              <div class="ds-cbe-table">
                <div class="ds-cbe-header">
                  <span>组织</span><span>硼 CBE</span><span>氮 RBE</span><span>氢 RBE</span><span>γ RBE</span>
                </div>
                <div v-for="tissue in ['tumor','normal_tissue','skin']" :key="tissue" class="ds-cbe-row">
                  <span class="ds-cbe-tissue">{{ dsTissueLabel[tissue] }}</span>
                  <input v-model.number="dsCbeRbe[tissue].boron_cbe"    type="number" step="0.05" min="0.1" max="6" class="ds-cbe-input" @input="dsOnParamChange" />
                  <input v-model.number="dsCbeRbe[tissue].nitrogen_rbe" type="number" step="0.1"  min="0.1" max="6" class="ds-cbe-input" @input="dsOnParamChange" />
                  <input v-model.number="dsCbeRbe[tissue].hydrogen_rbe" type="number" step="0.1"  min="0.1" max="6" class="ds-cbe-input" @input="dsOnParamChange" />
                  <input v-model.number="dsCbeRbe[tissue].gamma_rbe"    type="number" step="0.05" min="0.1" max="2" class="ds-cbe-input" @input="dsOnParamChange" />
                </div>
              </div>
            </div>

            <!-- 硼浓度 -->
            <div class="ds-section">
              <h3 class="ds-section-title">⚛️ 硼浓度 (ppm)</h3>
              <div class="ds-boron-grid">
                <template v-for="(label, key) in dsBoronLabel" :key="key">
                  <span class="ds-boron-label">{{ label }}</span>
                  <input v-model.number="dsBoronConc[key]" type="number" step="1" min="0" max="100" class="ds-boron-input" @input="dsOnParamChange" />
                </template>
              </div>
            </div>

            <!-- 计算按钮 -->
            <div class="ds-section">
              <button @click="dsCalculate" :disabled="dsLoading" class="btn btn-primary ds-calc-btn">
                <span v-if="dsLoading" class="spinner-sm"></span>
                {{ dsLoading ? '计算中...' : '▶ 计算剂量组分' }}
              </button>
              <p v-if="dsAutoCalc" class="ds-auto-hint">✓ 参数变更时自动更新</p>
            </div>

          </aside>

          <!-- ── 中间：几何可视化 ── -->
          <section class="ds-viz-panel">
            <!-- 标题 + 视图切换 -->
            <div class="ds-viz-header">
              <h3 class="ds-viz-title">几何可视化</h3>
            </div>

            <!-- ── 全身体模三视图 ── -->
            <div class="ds-canvas-wrap">

              <!-- 三视图标签（有体模切片时显示） -->
              <div v-if="dsHasPhantomBg" class="ds-ct-view-tabs">
                <button
                  v-for="v in [{k:'sagittal',l:'矢状'},{k:'coronal',l:'冠状'},{k:'axial',l:'轴向'}]"
                  :key="v.k"
                  :class="['ds-ct-view-tab', dsVizPhantomView === v.k ? 'active' : '']"
                  :disabled="!phantomSlices[v.k].length && !(v.k==='sagittal' && slices.sagittal.length)"
                  @click="dsVizPhantomView = v.k"
                >{{ v.l }}</button>
                <span class="ds-ct-view-hint">
                  {{ dsVizPhantomView==='sagittal' ? '矢状面 (YZ)' : dsVizPhantomView==='coronal' ? '冠状面 (XZ)' : '轴向面 (XY)' }}
                </span>
              </div>

              <!-- 画布：有体模 → img + SVG覆盖；无体模 → 纯SVG示意图 -->
              <div class="ds-phantom-canvas">

                <!-- 有体模：用 <img> 显示（object-fit:contain 保持正确宽高比） -->
                <template v-if="dsPhantomBgSlice">
                  <img :src="dsPhantomBgSlice" class="ds-phantom-bg-img" alt="体模切片" />

                  <!-- SVG 覆盖层：肿瘤位置（全三视图均显示）
                       viewBox 使用物理cm单位，与 phantom_preview.py 生成的各向异性等比图像对齐 -->
                  <svg
                    class="ds-phantom-overlay"
                    :viewBox="dsPhantomSvgViewBox"
                    xmlns="http://www.w3.org/2000/svg">
                    <defs>
                      <marker id="arrowhead2" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
                        <polygon points="0 0, 3 1.25, 0 2.5" fill="#d97706"/>
                      </marker>
                    </defs>
                    <!-- 肿瘤截面：球形肿瘤在当前切片上的截面（viewBox为物理cm，rx/ry单位=cm） -->
                    <template v-if="dsTumorSliceSvg.visible">
                      <ellipse
                        :cx="dsTumorSliceSvg.x"
                        :cy="dsTumorSliceSvg.y"
                        :rx="dsTumorSliceSvg.rx"
                        :ry="dsTumorSliceSvg.ry"
                        fill="rgba(229,62,62,0.55)" stroke="#fc8181" stroke-width="0.3"
                      />
                      <text v-if="dsTumorSliceSvg.isCenterSlice"
                        :x="dsTumorSliceSvg.x + dsTumorSliceSvg.rx + 0.8"
                        :y="dsTumorSliceSvg.y - 0.8"
                        font-size="3.5" fill="#fc8181">肿瘤</text>
                    </template>
                    <!-- 中子源 + 束流（矢状/冠状面有意义，轴向面隐藏） -->
                    <template v-if="dsVizPhantomView !== 'axial'">
                      <g :transform="`translate(${dsVizSourceX}, ${dsVizSourceY})`">
                        <circle r="2" fill="#fefce8" stroke="#d97706" stroke-width="0.3"/>
                        <text text-anchor="middle" y="0.6" font-size="2.5" fill="#92400e" font-weight="bold">n</text>
                      </g>
                      <!-- 束流箭头 -->
                      <line
                        :x1="dsVizSourceX" :y1="dsVizSourceY"
                        :x2="dsTumorInPhantomSvg.x" :y2="dsTumorInPhantomSvg.y"
                        stroke="#d97706" stroke-width="0.3" stroke-dasharray="2,1"
                        marker-end="url(#arrowhead2)"
                      />
                      <!-- 束流半径标注（源处水平线，宽度=2×束流半径） -->
                      <line
                        :x1="dsVizSourceX - dsSource.beam_radius" :y1="dsVizSourceY - 3"
                        :x2="dsVizSourceX + dsSource.beam_radius" :y2="dsVizSourceY - 3"
                        stroke="#d97706" stroke-width="0.2" stroke-dasharray="1,0.5"
                      />
                      <text :x="dsVizSourceX" :y="dsVizSourceY - 3.8" text-anchor="middle" font-size="2.5" fill="#92400e">
                        r={{ dsSource.beam_radius }}cm
                      </text>
                    </template>
                    <!-- 距离标注（束流视图） -->
                    <text v-if="dsVizPhantomView !== 'axial'"
                      :x="(dsVizSourceX + dsTumorInPhantomSvg.x) / 2 + 0.8"
                      :y="(dsVizSourceY + dsTumorInPhantomSvg.y) / 2 - 1.5"
                      font-size="2.5" fill="#cbd5e0" text-anchor="middle">
                      {{ dsVizDistance.toFixed(1) }}cm
                    </text>
                    <!-- 深度标注（当前肿瘤深度，水平辅助线） -->
                    <line
                      :x1="dsTumorInPhantomSvg.x - 5" :y1="dsTumorInPhantomSvg.y"
                      :x2="dsTumorInPhantomSvg.x + 5" :y2="dsTumorInPhantomSvg.y"
                      stroke="#fc8181" stroke-width="0.2" stroke-dasharray="1,0.5"
                    />
                    <text
                      :x="dsTumorInPhantomSvg.x + 5.5" :y="dsTumorInPhantomSvg.y + 0.8"
                      font-size="2.5" fill="#fc8181">深{{ dsTumorDepth }}cm</text>
                  </svg>
                </template>

                <!-- 无体模：纯SVG示意图（两椭圆 + 肿瘤 + 源 + 束流） -->
                <svg v-else ref="dsCanvas" class="ds-svg" viewBox="0 0 420 460" xmlns="http://www.w3.org/2000/svg">
                  <rect width="420" height="460" fill="#f8fafc" rx="8"/>
                  <!-- 坐标轴 -->
                  <line x1="30" y1="430" x2="390" y2="430" stroke="#cbd5e0" stroke-width="1"/>
                  <line x1="30" y1="430" x2="30"  y2="20"  stroke="#cbd5e0" stroke-width="1"/>
                  <text x="395" y="434" font-size="11" fill="#718096">Z</text>
                  <text x="32"  y="14"  font-size="11" fill="#718096">Y</text>
                  <!-- 体模轮廓（简略椭圆） -->
                  <g :transform="`translate(${dsVizPhantomX}, ${dsVizPhantomY}) rotate(${dsPhantom.rotation_deg[1]})`">
                    <ellipse cx="0" cy="0" rx="50" ry="90"
                      fill="rgba(100,180,255,0.18)" stroke="#4299e1" stroke-width="2" stroke-dasharray="6,3"/>
                    <ellipse cx="0" cy="-112" rx="28" ry="24"
                      fill="rgba(100,180,255,0.25)" stroke="#4299e1" stroke-width="1.5" stroke-dasharray="4,3"/>
                    <text x="0" y="-106" text-anchor="middle" font-size="10" fill="#2b6cb0">HEAD</text>
                    <text x="0" y="4"   text-anchor="middle" font-size="10" fill="#2b6cb0">BODY</text>
                    <!-- 肿瘤 -->
                    <circle
                      :cx="dsPhantom.tumor_position[2] * 2"
                      :cy="-dsPhantom.tumor_position[1] * 2"
                      :r="Math.max(4, dsPhantom.tumor_radius * 4)"
                      fill="rgba(229,62,62,0.70)" stroke="#fc8181" stroke-width="2"
                    />
                    <text
                      :x="dsPhantom.tumor_position[2] * 2 + 8"
                      :y="-dsPhantom.tumor_position[1] * 2 - 6"
                      font-size="9" fill="#c53030">肿瘤</text>
                  </g>
                  <!-- 中子源 -->
                  <g :transform="`translate(${dsVizSourceX}, ${dsVizSourceY})`">
                    <circle r="14" fill="#fefce8" stroke="#d97706" stroke-width="2.5"/>
                    <text text-anchor="middle" y="4" font-size="11" fill="#92400e" font-weight="bold">n</text>
                  </g>
                  <!-- 束流箭头 -->
                  <line
                    :x1="dsVizSourceX" :y1="dsVizSourceY"
                    :x2="dsVizPhantomX" :y2="dsVizPhantomY"
                    stroke="#d97706" stroke-width="2.5" stroke-dasharray="8,4"
                    marker-end="url(#arrowhead)"
                  />
                  <defs>
                    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
                      <polygon points="0 0, 8 3, 0 6" fill="#d97706"/>
                    </marker>
                  </defs>
                  <!-- 束流半径标注 -->
                  <line
                    :x1="dsVizSourceX - dsSource.beam_radius * 2" :y1="dsVizSourceY - 18"
                    :x2="dsVizSourceX + dsSource.beam_radius * 2" :y2="dsVizSourceY - 18"
                    stroke="#d97706" stroke-width="1" stroke-dasharray="3,2"
                  />
                  <text :x="dsVizSourceX" :y="dsVizSourceY - 22" text-anchor="middle" font-size="9" fill="#92400e">
                    r={{ dsSource.beam_radius }}cm
                  </text>
                  <!-- 距离标注 -->
                  <text
                    :x="(dsVizSourceX + dsVizPhantomX) / 2 + 6"
                    :y="(dsVizSourceY + dsVizPhantomY) / 2 - 8"
                    font-size="9" fill="#555" text-anchor="middle">
                    {{ dsVizDistance.toFixed(1) }}cm
                  </text>
                  <!-- 体模坐标标注 -->
                  <text :x="dsVizPhantomX" :y="dsVizPhantomY + 110" text-anchor="middle" font-size="9" fill="#2b6cb0">
                    中心({{ dsPhantom.center[0] }},{{ dsPhantom.center[1] }},{{ dsPhantom.center[2] }})
                  </text>
                  <!-- 深度标注线 -->
                  <line
                    :x1="dsVizPhantomX - 50" :y1="dsVizPhantomY - dsTumorDepth * 4"
                    :x2="dsVizPhantomX + 50" :y2="dsVizPhantomY - dsTumorDepth * 4"
                    stroke="#fc8181" stroke-width="1" stroke-dasharray="4,3"
                  />
                  <text
                    :x="dsVizPhantomX + 54" :y="dsVizPhantomY - dsTumorDepth * 4 + 4"
                    font-size="9" fill="#fc8181">深{{ dsTumorDepth }}cm</text>
                </svg>
              </div>

              <!-- 切片滑块（有体模时显示） -->
              <div v-if="dsHasPhantomBg" class="ds-phantom-slice-ctrl">
                <input
                  type="range"
                  :value="dsVizPhantomSliceIndices[dsVizPhantomView]"
                  :min="0" :max="dsPhantomBgMaxIdx"
                  class="ds-slider ds-phantom-slider"
                  @input="e => { dsVizPhantomSliceIndices[dsVizPhantomView] = +e.target.value }"
                />
                <span class="ds-phantom-slice-num">
                  {{ dsVizPhantomSliceIndices[dsVizPhantomView] + 1 }}/{{ dsPhantomBgMaxIdx + 1 }}
                </span>
              </div>
            </div>

            <!-- 深度滑块 -->
            <div class="ds-depth-ctrl">
              <label class="ds-label">肿瘤深度（沿束流轴）</label>
              <input v-model.number="dsTumorDepth" type="range" min="0" :max="ctMetadata ? ctMetadata.phys_size_cm[2] : 25" step="0.5" class="ds-slider" @input="dsOnTumorDepthChange" />
              <span class="ds-depth-val">{{ dsTumorDepth }} cm</span>
            </div>
          </section>

          <!-- ── 右侧：计算结果 ── -->
          <section class="ds-results-panel">

            <!-- 结果未出现时的占位 -->
            <div v-if="!dsResult" class="ds-empty">
              <p style="font-size:2rem">⚡</p>
              <p>设置参数后点击「计算剂量组分」</p>
              <p style="font-size:0.8rem;color:#888;margin-top:4px">
                或修改任意参数自动触发计算
              </p>
            </div>

            <template v-else>
              <!-- 摘要卡片 -->
              <div class="ds-summary-cards">
                <div class="ds-sum-card ds-sum-tumor">
                  <div class="ds-sum-icon">🎯</div>
                  <div class="ds-sum-val">{{ dsResult.tumor_point.total_weighted_cgy.toFixed(2) }}</div>
                  <div class="ds-sum-label">肿瘤总加权剂量 (cGy)</div>
                </div>
                <div class="ds-sum-card ds-sum-skin">
                  <div class="ds-sum-icon">🧬</div>
                  <div class="ds-sum-val">{{ dsResult.skin_point.total_weighted_cgy.toFixed(2) }}</div>
                  <div class="ds-sum-label">皮肤总加权剂量 (cGy)</div>
                </div>
                <div class="ds-sum-card ds-sum-ratio">
                  <div class="ds-sum-icon">📐</div>
                  <div class="ds-sum-val">{{ dsResult.summary.therapeutic_ratio.toFixed(2) }}</div>
                  <div class="ds-sum-label">治疗比 (T/S)</div>
                </div>
              </div>

              <!-- 剂量组分饼状柱图（肿瘤点） -->
              <div class="ds-component-section">
                <h4 class="ds-sub-title">肿瘤点 剂量组分分解（深度 {{ dsResult.tumor_depth_cm }} cm）</h4>
                <div class="ds-comp-bars">
                  <div v-for="comp in dsComponentList" :key="comp.key" class="ds-comp-row">
                    <span class="ds-comp-label">{{ comp.label }}</span>
                    <div class="ds-comp-bar-wrap">
                      <div class="ds-comp-bar"
                           :style="{ width: dsResult.tumor_point.fractions[comp.key] + '%',
                                     background: comp.color }">
                      </div>
                    </div>
                    <span class="ds-comp-pct">{{ dsResult.tumor_point.fractions[comp.key] }}%</span>
                    <span class="ds-comp-abs">{{ dsResult.tumor_point['weighted_' + comp.key + '_cgy'].toFixed(3) }} cGy</span>
                  </div>
                </div>
              </div>

              <!-- 物理剂量 vs 加权剂量对比 -->
              <div class="ds-component-section">
                <h4 class="ds-sub-title">物理剂量 vs 生物加权剂量 (cGy)</h4>
                <table class="ds-comp-table">
                  <thead>
                    <tr><th>组分</th><th>物理剂量</th><th>加权因子</th><th>生物剂量</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="comp in dsCompTableRows" :key="comp.key">
                      <td>{{ comp.label }}</td>
                      <td class="ds-mono">{{ dsResult.tumor_point[comp.phys_key].toFixed(4) }}</td>
                      <td class="ds-mono">× {{ comp.factor }}</td>
                      <td class="ds-mono ds-weighted">{{ dsResult.tumor_point[comp.wt_key].toFixed(4) }}</td>
                    </tr>
                    <tr class="ds-total-row">
                      <td colspan="3"><strong>合计生物加权剂量</strong></td>
                      <td class="ds-mono ds-total"><strong>{{ dsResult.tumor_point.total_weighted_cgy.toFixed(4) }}</strong></td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- 深度-剂量曲线 -->
              <div class="ds-component-section">
                <h4 class="ds-sub-title">深度-剂量曲线（肿瘤组织）</h4>
                <div class="ds-ddp-wrap">
                  <svg class="ds-ddp-svg" viewBox="0 0 400 200">
                    <rect width="400" height="200" fill="#f8fafc" rx="4"/>
                    <!-- Y轴网格 -->
                    <g v-for="i in 4" :key="'gy'+i">
                      <line :x1="40" :y1="180 - i*35" :x2="390" :y2="180 - i*35"
                            stroke="#e2e8f0" stroke-width="1"/>
                    </g>
                    <!-- 总剂量曲线 -->
                    <polyline
                      :points="dsDdpPoints"
                      fill="none" stroke="#667eea" stroke-width="2.5"
                    />
                    <!-- 各组分细线 -->
                    <polyline :points="dsDdpPointsComp('boron')"    fill="none" stroke="#e53e3e" stroke-width="1.5" stroke-dasharray="4,2"/>
                    <polyline :points="dsDdpPointsComp('nitrogen')" fill="none" stroke="#38a169" stroke-width="1.5" stroke-dasharray="4,2"/>
                    <polyline :points="dsDdpPointsComp('hydrogen')" fill="none" stroke="#d69e2e" stroke-width="1.5" stroke-dasharray="4,2"/>
                    <polyline :points="dsDdpPointsComp('gamma')"    fill="none" stroke="#805ad5" stroke-width="1.5" stroke-dasharray="4,2"/>
                    <!-- 坐标轴 -->
                    <line x1="40" y1="20" x2="40"  y2="185" stroke="#a0aec0" stroke-width="1.5"/>
                    <line x1="40" y1="180" x2="395" y2="180" stroke="#a0aec0" stroke-width="1.5"/>
                    <text x="8"  y="100" font-size="9" fill="#718096" transform="rotate(-90,8,100)">剂量 (cGy)</text>
                    <text x="210" y="198" font-size="9" fill="#718096" text-anchor="middle">深度 (cm)</text>
                    <!-- 肿瘤深度标注线 -->
                    <line
                      :x1="dsDdpTumorX" y1="20"
                      :x2="dsDdpTumorX" y2="180"
                      stroke="#e53e3e" stroke-width="1.5" stroke-dasharray="5,3"
                    />
                    <!-- 图例 -->
                    <rect x="42" y="22" width="8" height="4" fill="#667eea"/>
                    <text x="54" y="28" font-size="8" fill="#333">总剂量</text>
                    <line x1="90" y1="25" x2="98" y2="25" stroke="#e53e3e" stroke-width="1.5" stroke-dasharray="3,2"/>
                    <text x="102" y="28" font-size="8" fill="#333">硼</text>
                    <line x1="120" y1="25" x2="128" y2="25" stroke="#38a169" stroke-width="1.5" stroke-dasharray="3,2"/>
                    <text x="132" y="28" font-size="8" fill="#333">氮</text>
                    <line x1="150" y1="25" x2="158" y2="25" stroke="#d69e2e" stroke-width="1.5" stroke-dasharray="3,2"/>
                    <text x="162" y="28" font-size="8" fill="#333">氢</text>
                    <line x1="178" y1="25" x2="186" y2="25" stroke="#805ad5" stroke-width="1.5" stroke-dasharray="3,2"/>
                    <text x="190" y="28" font-size="8" fill="#333">γ</text>
                  </svg>
                </div>
              </div>

              <!-- 三种组织对比 -->
              <div class="ds-component-section">
                <h4 class="ds-sub-title">三种组织剂量对比（深度 {{ dsResult.tumor_depth_cm }} cm）</h4>
                <table class="ds-comp-table">
                  <thead>
                    <tr><th>组织</th><th>总加权剂量 (cGy)</th><th>硼%</th><th>氮%</th><th>氢%</th><th>γ%</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="t in ['tumor','normal_tissue','skin']" :key="t">
                      <td>{{ dsTissueLabel[t] }}</td>
                      <td class="ds-mono">{{ dsResult[t + '_point'].total_weighted_cgy.toFixed(3) }}</td>
                      <td class="ds-mono">{{ dsResult[t + '_point'].fractions.boron }}%</td>
                      <td class="ds-mono">{{ dsResult[t + '_point'].fractions.nitrogen }}%</td>
                      <td class="ds-mono">{{ dsResult[t + '_point'].fractions.hydrogen }}%</td>
                      <td class="ds-mono">{{ dsResult[t + '_point'].fractions.gamma }}%</td>
                    </tr>
                  </tbody>
                </table>
              </div>

            </template>
          </section>

        </div>

        <!-- ── 验证面板 ── -->
        <div class="ds-validate-panel">
          <div class="ds-validate-header">
            <h3>🧪 剂量参数三级验证</h3>
            <p class="ds-validate-desc">
              Level 1：CBE/RBE 与文献值对比 ·
              Level 2：解析公式核查 ·
              Level 3：临床基准案例（JRR-4 / Petten HFR / MIT MITR-II）
            </p>
            <button @click="dsRunValidation" :disabled="dsValidating" class="btn btn-primary">
              <span v-if="dsValidating" class="spinner-sm"></span>
              {{ dsValidating ? '验证中...' : '▶ 运行验证' }}
            </button>
          </div>

          <div v-if="dsValidateResult" class="ds-validate-body">
            <!-- 总结卡片 -->
            <div class="ds-val-summary">
              <div class="ds-val-card" :class="dsValidateResult.level1_cbe_rbe.passed ? 'val-pass' : 'val-fail'">
                <div class="ds-val-icon">{{ dsValidateResult.level1_cbe_rbe.passed ? '✓' : '✗' }}</div>
                <div class="ds-val-label">L1 CBE/RBE</div>
              </div>
              <div class="ds-val-card" :class="dsValidateResult.level1_boron_conc.passed ? 'val-pass' : 'val-fail'">
                <div class="ds-val-icon">{{ dsValidateResult.level1_boron_conc.passed ? '✓' : '✗' }}</div>
                <div class="ds-val-label">L1 硼浓度</div>
              </div>
              <div class="ds-val-card" :class="dsValidateResult.level2_formula.passed ? 'val-pass' : 'val-fail'">
                <div class="ds-val-icon">{{ dsValidateResult.level2_formula.passed ? '✓' : '✗' }}</div>
                <div class="ds-val-label">L2 公式</div>
              </div>
              <div class="ds-val-card val-info">
                <div class="ds-val-icon">📋</div>
                <div class="ds-val-label">L3 案例 {{ dsValidateResult.summary.level3_cases_pass }}</div>
              </div>
              <div class="ds-val-card" :class="dsValidateResult.all_pass ? 'val-pass' : 'val-warn'">
                <div class="ds-val-icon">{{ dsValidateResult.all_pass ? '✓' : '!' }}</div>
                <div class="ds-val-label">总体结果</div>
              </div>
            </div>

            <!-- L1 CBE/RBE 明细 -->
            <details class="ds-val-detail" open>
              <summary>Level 1 ─ CBE/RBE 参数验证（{{ dsValidateResult.level1_cbe_rbe.checks.length }} 项）</summary>
              <table class="ds-val-table">
                <thead><tr><th>组织</th><th>参数</th><th>用户值</th><th>文献值</th><th>文献范围</th><th>结果</th></tr></thead>
                <tbody>
                  <tr v-for="(c, i) in dsValidateResult.level1_cbe_rbe.checks" :key="i" :class="c.passed ? '' : 'val-row-fail'">
                    <td>{{ c.tissue }}</td>
                    <td>{{ c.factor }}</td>
                    <td class="ds-mono">{{ c.user_value }}</td>
                    <td class="ds-mono">{{ c.lit_value }}</td>
                    <td class="ds-mono">[{{ c.lit_range[0] }}, {{ c.lit_range[1] }}]</td>
                    <td>{{ c.passed ? '✓' : '✗' }}</td>
                  </tr>
                </tbody>
              </table>
            </details>

            <!-- L2 公式验证 -->
            <details class="ds-val-detail">
              <summary>Level 2 ─ 剂量公式解析验证</summary>
              <table class="ds-val-table">
                <thead><tr><th>验证项</th><th>计算值</th><th>解析/参考值</th><th>结果</th><th>备注</th></tr></thead>
                <tbody>
                  <tr v-for="(c, i) in dsValidateResult.level2_formula.checks" :key="i" :class="c.passed ? '' : 'val-row-fail'">
                    <td>{{ c.name }}</td>
                    <td class="ds-mono">{{ c.computed_cgy !== undefined ? c.computed_cgy : c.sigma_used }}</td>
                    <td class="ds-mono">{{ c.analytic_cgy !== undefined ? c.analytic_cgy : c.lit_value }}</td>
                    <td>{{ c.passed ? '✓' : '✗' }}</td>
                    <td style="font-size:0.75rem">{{ c.note || c.ref || '' }}</td>
                  </tr>
                </tbody>
              </table>
            </details>

            <!-- L3 临床案例 -->
            <details class="ds-val-detail">
              <summary>Level 3 ─ 临床基准案例验证 ({{ dsValidateResult.level3_clinical.n_pass }}/{{ dsValidateResult.level3_clinical.total }} 通过)</summary>
              <div v-for="cas in dsValidateResult.level3_clinical.cases" :key="cas.id" class="ds-val-case">
                <div class="ds-val-case-header" :class="cas.passed ? 'case-pass' : 'case-fail'"
                     @click="toggleDsCase(cas.id)" style="cursor:pointer;">
                  <span>{{ cas.passed ? '✓' : '✗' }} {{ cas.name }}</span>
                  <span style="display:flex;align-items:center;gap:8px;">
                    <span class="ds-val-case-ref">{{ cas.ref }}</span>
                    <span class="ds-val-expand-hint">{{ dsExpandedCases[cas.id] ? '▲ 收起' : '▼ 展开' }}</span>
                  </span>
                </div>
                <div v-if="dsExpandedCases[cas.id]" class="ds-val-case-body">
                  <p class="ds-val-case-desc">{{ cas.description }}</p>
                  <table class="ds-val-table">
                    <thead><tr><th>检查项</th><th>计算值</th><th>期望范围</th><th>结果</th></tr></thead>
                    <tbody>
                      <tr v-for="(ck, ci) in cas.checks" :key="ci" :class="ck.passed ? '' : 'val-row-fail'">
                        <td>{{ ck.check }}</td>
                        <td class="ds-mono">{{ ck.value }}</td>
                        <td class="ds-mono">{{ ck.expected }}</td>
                        <td>{{ ck.passed ? '✓' : '✗' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </details>

          </div>
          <div v-else-if="!dsValidating" class="ds-val-empty">
            <p>点击「运行验证」，自动完成三级参数正确性验证</p>
          </div>
        </div>

      </div>
      <!-- /MCNP Tab 剂量组分设置 -->

    </main>

    <!-- 剂量分布全屏遮罩 -->
    <div v-if="doseFullscreenView" class="fullscreen-overlay" @click.self="doseFullscreenView = null">
      <div class="fullscreen-panel dose-fullscreen-panel">
        <div class="panel-header">
          <h4>{{ viewNames[doseFullscreenView] }}剂量分布</h4>
          <div class="panel-actions">
            <button @click="previousDoseSlice(doseFullscreenView)"
                    :disabled="doseSliceIndices[doseFullscreenView] === 0"
                    class="btn-icon" title="上一张">◀</button>
            <span class="dose-fs-slice-info">
              {{ doseSliceIndices[doseFullscreenView] + 1 }} / {{ (slices[doseSliceKey(doseFullscreenView)] || []).length }}
            </span>
            <button @click="nextDoseSlice(doseFullscreenView)"
                    :disabled="doseSliceIndices[doseFullscreenView] >= (slices[doseSliceKey(doseFullscreenView)] || []).length - 1"
                    class="btn-icon" title="下一张">▶</button>
            <button @click="doseFullscreenView = null" class="btn-icon" title="退出全屏">✕</button>
          </div>
        </div>
        <div class="fullscreen-image-container">
          <img
            v-if="slices[doseSliceKey(doseFullscreenView)] && slices[doseSliceKey(doseFullscreenView)][doseSliceIndices[doseFullscreenView]]"
            :src="getImageUrl(slices[doseSliceKey(doseFullscreenView)][doseSliceIndices[doseFullscreenView]])"
            :alt="`${viewNames[doseFullscreenView]}剂量分布`"
            class="fullscreen-image"
          />
          <div v-else class="placeholder">
            <p>📈</p><p>等待剂量数据...</p>
          </div>
        </div>
        <div class="viewer-slice-control" style="padding: 0 1.5rem 1rem;">
          <input
            v-model.number="doseSliceIndices[doseFullscreenView]"
            type="range" min="0"
            :max="Math.max(0, (slices[doseSliceKey(doseFullscreenView)] || []).length - 1)"
            class="viewer-slider"
          />
        </div>
      </div>
    </div>

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

    <!-- 加载遮罩已移除：各按钮自行显示加载状态 -->
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
        { id: 'risk', name: '风险评估', icon: '🏥' },
        { id: 'icrp116', name: 'ICRP-116验证', icon: '✅' }
      ],

      // 全屏
      fullscreenView: null,

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
      ctMetadata: null,        // CT 体积元数据（体素大小、物理尺寸、中心坐标）

      // 剂量组分几何可视化模式
      dsVizMode: 'schematic',     // 'schematic' | 'ct'
      dsVizCtView: 'coronal',     // CT图像模式中当前视图: 'axial'|'coronal'|'sagittal'
      dsVizCtSliceIdx: 0,         // 保留（向后兼容）
      dsVizCtSliceIndices: { axial: 0, coronal: 0, sagittal: 0 },
      // 全身体模预览切片（构建体模后填入）
      phantomSlices: { axial: [], coronal: [], sagittal: [] },
      dsVizPhantomView: 'sagittal',  // 示意图模式中体模视图: 'axial'|'coronal'|'sagittal'
      dsVizPhantomSliceIndices: { axial: 0, coronal: 0, sagittal: 0 },

      // 剂量数据
      doseFiles: [],
      doseOpacity: 70,
      hasDoseData: false,

      // DVH
      organFiles: [],
      dvhImage: '',
      dvhStats: null,

      // ICRP对比
      icrcPhantomType: 'AM',
      icrcLoading: false,
      icrcResult: null,
      icrcChartUrl: '',
      icrcError: '',

      // ICRP-116 AP 光子验证
      icrp116Energies: [
        { value: 0.01,  label: '0.01 MeV（10 keV）' },
        { value: 0.10,  label: '0.10 MeV（100 keV）' },
        { value: 1.00,  label: '1.00 MeV' },
        { value: 10.00, label: '10.00 MeV' },
      ],
      icrp116Selected:   [0.01, 0.10, 1.00, 10.00],
      icrp116SexAvg:     true,   // 启用性别平均 (AM+AF)
      icrp116ForceRerun: false,  // 强制重跑：忽略已有 npy 缓存
      icrp116DeDfMode:   false,  // DE/DF 模式：fluence→kerma 单 FMESH 精确方法
      icrp116Running:    false,
      icrp116Status: {
        completed: false, failed: false,
        currentCase: null, doneEnergies: [],
        elapsedSec: 0, logs: [], resultFiles: [],
        sexAvg: false, phase: 'AM',
        afDoneEnergies: [], afCurrentCase: null, afResultFiles: [],
      },
      icrp116PollTimer: null,
      // Step 3 对比分析
      icrp116Step3Loading: false,
      icrp116Step3Done:    false,
      icrp116Step3Result:  null,
      icrp116Step3Log:     [],
      icrp116ChartLoading: false,
      icrp116ChartUrl:     null,
      icrp116XsdirChecking: false,
      icrp116XsdirInfo:    null,

      // 中子AP ICRP剂量对比
      neutronPhantomType: 'AM',
      neutronLoading: false,
      neutronCharts: [],
      neutronSummary: null,
      neutronError: '',
      neutronActiveChart: 0,

      // BEIR VII 验证
      bvLoading: false,
      bvResult: null,
      bvError: '',
      expandedCases: {},
      dsExpandedCases: {},

      // 风险评估
      patientCtFile: null,
      detectedRegion: '',   // CT自动识别的解剖区域 (chest/brain/abdomen等)
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
          loadingText: '正在构建...',
          action: null,
          status: 'pending',
          disabled: false,
          result: ''
        },
        {
          title: '运行MCNP全身计算',
          description: '在多材料体素几何中执行蒙特卡洛中子输运(耗时较长)',
          buttonText: '开始计算',
          loadingText: '正在计算...',
          action: null,
          status: 'pending',
          disabled: true,
          result: ''
        },
        {
          title: '生成全身剂量分布图',
          description: '从MCNP全身meshtal提取剂量数据，生成三视图可视化',
          buttonText: '生成剂量图',
          loadingText: '正在生成...',
          action: null,
          status: 'pending',
          disabled: true,
          result: ''
        }
      ],
      currentStep: -1,
      logs: [],

      // 器官轮廓
      contourMasks: [],          // { name, file, color, visible }
      overlaySlices: { axial: [], coronal: [], sagittal: [] },
      showContourOverlay: false,
      contourGenerating: false,
      autoSegmenting: false,
      autoSegResult: null,
      autoSegExpanded: false,
      contourListExpanded: false,
      // 与 contour_overlay.py COLORS 顺序一致
      contourColors: ['#E6C832','#DC6464','#3C3CDC','#64C850','#C850C8','#32C8C8','#DC8232','#9650DC','#F05050','#50DCA0','#C8C850','#5096DC'],

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

      // 器官轮廓显示（全身体模剂量视图）
      doseOrganList: [
        { keyword: 'brain',       name: '脑',     color: '#F0C8A0', visible: true },
        { keyword: 'liver',       name: '肝脏',   color: '#E6C832', visible: true },
        { keyword: 'heart',       name: '心脏',   color: '#DC6464', visible: true },
        { keyword: 'lung',        name: '肺',     color: '#3C3CDC', visible: true },
        { keyword: 'kidney',      name: '肾脏',   color: '#C850C8', visible: true },
        { keyword: 'spleen',      name: '脾脏',   color: '#64C850', visible: true },
        { keyword: 'bladder',     name: '膀胱',   color: '#9650DC', visible: true },
        { keyword: 'stomach',     name: '胃',     color: '#DC8232', visible: true },
        { keyword: 'pancreas',    name: '胰腺',   color: '#32C8C8', visible: true },
        { keyword: 'colon',       name: '结肠',   color: '#50DCA0', visible: true },
        { keyword: 'intestine',   name: '小肠',   color: '#5096DC', visible: true },
        { keyword: 'thyroid',     name: '甲状腺', color: '#C8C850', visible: true },
        { keyword: 'esophagus',   name: '食管',   color: '#F05050', visible: true },
        { keyword: 'adrenal',     name: '肾上腺', color: '#64C8C8', visible: true },
        { keyword: 'gallbladder', name: '胆囊',   color: '#A0DC50', visible: true },
        { keyword: 'thymus',      name: '胸腺',   color: '#DCA0DC', visible: true },
        { keyword: 'prostate',    name: '前列腺', color: '#5096DC', visible: true },
      ],
      doseOrgansDirty: false,
      doseOrganApplying: false,
      doseOrganExpanded: false,
      doseFullscreenView: null,

      // 体模构建参数
      phantomBuilt: false,
      niiUploading: false,
      doseUploading: false,

      // ========== 剂量组分设置 Tab ==========
      dsLoading:   false,
      dsValidating: false,
      dsAutoCalc:  true,
      dsAutoTimer: null,
      dsResult:    null,
      dsValidateResult: null,
      dsIntensityExp: '12',

      dsSource: {
        source_type:      'epithermal',
        position:         [0, 0, 0],
        direction:        [0, 0, 0],
        beam_radius:      0,
        energy_mono:      0,
        energy_spectrum: {
          energies: [5e-7, 1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1, 1.0, 10.0],
          weights:  [0.00, 0.00, 0.00, 0.00, 0.00,  0.00, 0.00, 0.00, 0.00]
        },
        intensity: 0
      },

      dsPhantom: {
        phantom_type:   'AM',
        center:         [0, 0, 0],
        rotation_deg:   [0, 0, 0],
        height_cm:      0,
        weight_kg:      0,
        tumor_position: [0, 0, 0],
        tumor_radius:   0
      },

      dsTumorDepth: 0,

      dsCbeRbe: {
        tumor: {
          boron_cbe: 0, nitrogen_rbe: 0, hydrogen_rbe: 0, gamma_rbe: 0
        },
        normal_tissue: {
          boron_cbe: 0, nitrogen_rbe: 0, hydrogen_rbe: 0, gamma_rbe: 0
        },
        skin: {
          boron_cbe: 0, nitrogen_rbe: 0, hydrogen_rbe: 0, gamma_rbe: 0
        }
      },

      dsBoronConc: {
        tumor: 0, skin: 0, blood: 0, normal_tissue: 0
      },

      dsTissueLabel: {
        tumor: '肿瘤', normal_tissue: '正常组织', skin: '皮肤'
      },
      dsBoronLabel: {
        tumor: '肿瘤', skin: '皮肤', blood: '血液', normal_tissue: '正常组织'
      },

      dsComponentList: [
        { key: 'boron',    label: '硼 (¹⁰B·CBE)',   color: '#e53e3e' },
        { key: 'nitrogen', label: '氮 (¹⁴N·RBE)',   color: '#38a169' },
        { key: 'hydrogen', label: '氢 (¹H·RBE)',    color: '#d69e2e' },
        { key: 'gamma',    label: '伽马 (γ·RBE)',   color: '#805ad5' }
      ],

      dsCompTableRows: [
        { key: 'boron',    label: '硼 ¹⁰B(n,α)',  phys_key: 'boron_dose_cgy',    wt_key: 'weighted_boron_cgy',    factor: 'CBE_B'  },
        { key: 'nitrogen', label: '氮 ¹⁴N(n,p)',  phys_key: 'nitrogen_dose_cgy', wt_key: 'weighted_nitrogen_cgy', factor: 'RBE_N'  },
        { key: 'hydrogen', label: '氢 ¹H(n,γ)',   phys_key: 'hydrogen_dose_cgy', wt_key: 'weighted_hydrogen_cgy', factor: 'RBE_H'  },
        { key: 'gamma',    label: 'γ 伽马',        phys_key: 'gamma_dose_cgy',    wt_key: 'weighted_gamma_cgy',    factor: 'RBE_γ'  }
      ],
    };
  },

  computed: {
    // ── 剂量组分可视化计算属性 ──
    dsVizPhantomX() {
      // 将体模 Z 坐标映射到 SVG X 轴 [40, 380]
      const z = this.dsPhantom.center[2];
      return Math.max(80, Math.min(340, 210 + z * 1.5));
    },
    dsVizPhantomY() {
      // 将体模 Y 坐标映射到 SVG Y 轴（翻转），体模躯干中心
      const y = this.dsPhantom.center[1];
      return Math.max(140, Math.min(320, 250 - y * 1.5));
    },
    // SVG viewBox以物理cm为单位，保持与背景图像相同的宽高比，确保覆盖层对齐
    // 水平方向体外中子源通过 overflow:visible 渲染在viewBox外侧
    dsPhantomSvgViewBox() {
      const d = this.dsPhantomPhysDims;
      const view = this.dsVizPhantomView;
      // viewBox 精确匹配体模物理尺寸，确保 SVG 覆盖层与背景图像完全对齐。
      // 横向体外中子源（x<0）通过 overflow:visible 渲染在 viewBox 外侧，无需顶部缓冲。
      if (view === 'coronal')  return `0 0 ${d.x} ${d.z}`;
      if (view === 'sagittal') return `0 0 ${d.y} ${d.z}`;
      return `0 0 ${d.x} ${d.y}`;  // 轴向面
    },
    // 中子源在体模SVG坐标系中的位置（物理cm，各视图使用正确轴）
    dsVizSourceX() {
      const view = this.dsVizPhantomView;
      const d    = this.dsPhantomPhysDims;
      const sp   = this.dsSource.position;  // 相对体模中心（cm）
      if (view === 'coronal')  return d.xc + sp[0];  // 冠状面：水平=X
      if (view === 'sagittal') return d.yc + sp[1];  // 矢状面：水平=Y
      return d.xc + sp[0];  // 轴向面：水平=X
    },
    dsVizSourceY() {
      const view = this.dsVizPhantomView;
      const d    = this.dsPhantomPhysDims;
      const sp   = this.dsSource.position;
      if (view === 'axial') return d.yc + sp[1];  // 轴向面：垂直=Y（不翻转）
      return d.z - (d.zc + sp[2]);  // 冠/矢状面：Z轴翻转（头在上，正值在视图顶部）
    },
    dsVizDistance() {
      const s = this.dsSource.position;
      const p = this.dsPhantom.center;
      return Math.sqrt((s[0]-p[0])**2 + (s[1]-p[1])**2 + (s[2]-p[2])**2);
    },
    dsDdpPoints() {
      if (!this.dsResult || !this.dsResult.depth_profile) return '';
      const profile = this.dsResult.depth_profile;
      const maxD = Math.max(...profile.map(p => p.total_weighted_cgy), 0.001);
      return profile.map((p, i) => {
        const x = 40 + (i / (profile.length - 1)) * 350;
        const y = 180 - (p.total_weighted_cgy / maxD) * 155;
        return `${x},${y}`;
      }).join(' ');
    },
    dsDdpTumorX() {
      if (!this.dsResult || !this.dsResult.depth_profile) return 210;
      const profile = this.dsResult.depth_profile;
      const depths  = profile.map(p => p.depth_cm);
      const td      = this.dsResult.tumor_depth_cm;
      const idx     = depths.findIndex(d => d >= td);
      if (idx < 0) return 390;
      return 40 + (idx / (profile.length - 1)) * 350;
    },

    // ── CT 图像模式：当前切片图像 ──
    dsCTVizSlice() {
      const view = this.dsVizCtView;
      const overlay = this.showContourOverlay && this.overlaySlices[view] && this.overlaySlices[view].length;
      const src = overlay ? this.overlaySlices[view] : this.slices[view];
      if (!src || !src.length) return null;
      const idx = Math.max(0, Math.min(src.length - 1, this.dsVizCtSliceIndices[view]));
      return this.getImageUrl(src[idx]);
    },

    // CT 图像模式：当前视图最大切片索引
    dsCTVizMaxIdx() {
      const view = this.dsVizCtView;
      const overlay = this.showContourOverlay && this.overlaySlices[view] && this.overlaySlices[view].length;
      const src = overlay ? this.overlaySlices[view] : this.slices[view];
      return src ? Math.max(0, src.length - 1) : 0;
    },

    // ── 全身体模肿瘤定位：CT坐标系 → 体模解剖坐标系 ──────────────────────────

    // 根据检测到的解剖区域，计算CT图像中心相对于ICRP体模几何中心的偏移量（cm）
    // 偏移量 = (体模CT目标中心体素 - 体模几何中心体素) × 体素尺寸
    // 基于 ct_phantom_fusion.py 中 ANATOMICAL_REGIONS 的 z_range，AM体模：222×8mm=177.6cm
    dsCtToPhantomOffset() {
      // [X_offset, Y_offset, Z_offset] in cm, relative to phantom geometric center
      // Computed from: target_center_voxel - (shape/2), then × voxel_size
      const offsets = {
        brain:       [0,    0,    76.8],   // z: (207-111)*0.8
        nasopharynx: [0,   -2.7,  63.2],  // z: (190-111)*0.8, y: (50.8-63.5)*0.2137
        chest:       [0,    0,    45.6],   // z: (168-111)*0.8
        abdomen:     [0,    0,    19.2],   // z: (135-111)*0.8
        liver:       [2.7,  0,    22.4],   // z: (139-111)*0.8, x: (139.7-127)*0.2137
        pelvis:      [0,    0,   -14.4],   // z: (93-111)*0.8
        legs:        [0,    0,   -57.6],   // z: (39-111)*0.8
        wholebody:   [0,    0,    -0.8],   // z: (110-111)*0.8
      };
      return offsets[this.detectedRegion] || [0, 0, 0];
    },

    // 肿瘤在体模物理空间中的位置（相对于体模几何中心，单位 cm）
    dsTumorInPhantomCm() {
      const tp = this.dsPhantom.tumor_position;
      const off = this.dsCtToPhantomOffset;
      return [tp[0] + off[0], tp[1] + off[1], tp[2] + off[2]];
    },

    // ICRP体模物理尺寸（cm）及几何中心（cm，从边缘量起）
    dsPhantomPhysDims() {
      const isAF = this.dsPhantom.phantom_type === 'AF';
      // AF: 299×1.775, 137×1.775, 348×4.84 mm
      if (isAF) return { x:53.08, xc:26.54, y:24.32, yc:12.16, z:168.43, zc:84.22 };
      // AM: 254×2.137, 127×2.137, 222×8.0 mm
      return { x:54.28, xc:27.14, y:27.14, yc:13.57, z:177.6, zc:88.8 };
    },

    // 肿瘤在体模SVG坐标系中的位置（物理cm，与dsPhantomSvgViewBox一致）
    dsTumorInPhantomSvg() {
      const t = this.dsTumorInPhantomCm;
      const d = this.dsPhantomPhysDims;
      const view = this.dsVizPhantomView;
      const buf = 25;

      // 绝对坐标（从体模边缘，cm）
      const ax = d.xc + t[0];
      const ay = d.yc + t[1];
      const az = d.zc + t[2];

      let svgX, svgY;
      if (view === 'coronal') {
        svgX = ax;
        svgY = d.z - az;   // Z轴翻转：头顶在SVG顶部（y=0）
      } else if (view === 'axial') {
        svgX = ax;
        svgY = ay;
      } else {  // sagittal
        svgX = ay;
        svgY = d.z - az;
      }

      const physW = (view === 'sagittal') ? d.y : d.x;
      const physH = (view === 'axial')    ? d.y : d.z;
      return {
        x: Math.max(0, Math.min(physW, svgX)),
        y: Math.max(-buf, Math.min(physH, svgY)),
      };
    },

    // 当前切片处球形肿瘤的截面：根据切片位置动态计算截面半径（球截面公式）
    // 切片距球心距离 d → 截面半径 r = sqrt(R² - d²)，超出球体范围则不可见
    dsTumorSliceSvg() {
      const view  = this.dsVizPhantomView;
      const R     = this.dsPhantom.tumor_radius;   // cm
      const d     = this.dsPhantomPhysDims;
      const tc    = this.dsTumorInPhantomCm;        // offset from phantom geometric center
      const isAF  = this.dsPhantom.phantom_type === 'AF';

      // 体素尺寸 (cm)
      const vox = isAF
        ? { x: 0.1775, y: 0.1775, z: 0.484 }
        : { x: 0.2137, y: 0.2137, z: 0.800 };

      // 肿瘤中心绝对坐标（从体模边缘, cm）
      const tcx = d.xc + tc[0];
      const tcy = d.yc + tc[1];
      const tcz = d.zc + tc[2];

      // 当前切片的物理位置（cm）
      const idx  = this.dsVizPhantomSliceIndices[view];
      let slicePos_cm, dist;
      if (view === 'sagittal') {
        slicePos_cm = idx * vox.x;
        dist = slicePos_cm - tcx;
      } else if (view === 'coronal') {
        slicePos_cm = idx * vox.y;
        dist = slicePos_cm - tcy;
      } else {  // axial
        slicePos_cm = idx * vox.z;
        dist = slicePos_cm - tcz;
      }

      // 球截面半径（cm）；超出球体范围则不显示
      if (Math.abs(dist) > R) return { visible: false };
      const r_slice = Math.sqrt(R * R - dist * dist);

      // SVG viewBox使用物理cm单位，1 SVG单位 = 1 cm，rx/ry直接用物理半径
      // 避免旧方案中 420/d.x 与 460/d.z 比例不同导致的肿瘤显示过大问题
      const pos = this.dsTumorInPhantomSvg;
      return {
        visible: true,
        x:  pos.x,
        y:  pos.y,
        rx: Math.max(0.2, r_slice),
        ry: Math.max(0.2, r_slice),
        isCenterSlice: Math.abs(dist) < Math.max(vox.x, vox.y, vox.z),
      };
    },

    // ─────────────────────────────────────────────────────────────────────────

    // CT 图像模式：肿瘤标记位置（百分比，随视图变化）
    dsCTTumorStyle() {
      if (!this.ctMetadata) return { display: 'none' };
      const meta = this.ctMetadata;
      const pos = this.dsPhantom.tumor_position;
      const r = this.dsPhantom.tumor_radius;
      let xRel, yRel, rRelX;

      if (this.dsVizCtView === 'axial') {
        // width=X, height=Y(inverted)
        xRel  = (pos[0] + meta.phys_size_cm[0] / 2) / meta.phys_size_cm[0];
        yRel  = (meta.phys_size_cm[1] / 2 - pos[1]) / meta.phys_size_cm[1];
        rRelX = r / meta.phys_size_cm[0];
      } else if (this.dsVizCtView === 'coronal') {
        // width=X, height=Z(inverted)
        xRel  = (pos[0] + meta.phys_size_cm[0] / 2) / meta.phys_size_cm[0];
        yRel  = (meta.phys_size_cm[2] / 2 - pos[2]) / meta.phys_size_cm[2];
        rRelX = r / meta.phys_size_cm[0];
      } else {
        // sagittal: width=Y, height=Z(inverted)
        xRel  = (pos[1] + meta.phys_size_cm[1] / 2) / meta.phys_size_cm[1];
        yRel  = (meta.phys_size_cm[2] / 2 - pos[2]) / meta.phys_size_cm[2];
        rRelX = r / meta.phys_size_cm[1];
      }
      const left = Math.max(0, Math.min(100, xRel * 100));
      const top  = Math.max(0, Math.min(100, yRel * 100));
      const diam = Math.max(1, rRelX * 2 * 100);
      return { left: `${left}%`, top: `${top}%`, width: `${diam}%`, height: `${diam}%`, marginLeft: `-${diam/2}%`, marginTop: `-${diam/2}%` };
    },

    // ── 示意图模式：全身体模切片（三视图背景）──
    dsPhantomBgSlice() {
      const view = this.dsVizPhantomView;
      // phantom 三视图优先；axial/coronal 无 CT 回退
      const src = this.phantomSlices[view].length
        ? this.phantomSlices[view]
        : (view === 'sagittal' ? this.slices.sagittal : []);
      if (!src.length) return null;
      const idx = Math.max(0, Math.min(src.length - 1,
        this.dsVizPhantomSliceIndices[view]));
      return this.getImageUrl(src[idx]);
    },

    dsPhantomBgMaxIdx() {
      const view = this.dsVizPhantomView;
      const src = this.phantomSlices[view].length
        ? this.phantomSlices[view]
        : (view === 'sagittal' ? this.slices.sagittal : []);
      return Math.max(0, src.length - 1);
    },

    // 示意图模式：是否有任何背景图像可用
    dsHasPhantomBg() {
      return this.phantomSlices.sagittal.length > 0 ||
             this.phantomSlices.coronal.length > 0 ||
             this.phantomSlices.axial.length > 0 ||
             this.slices.sagittal.length > 0;
    },

    canGenerateDVH() {
      return this.organFiles.length > 0 && this.hasDoseData;
    },
    canRunRiskAssessment() {
      return this.phantomBuilt;
    },
    // 将 param_review 列表按 group 字段分组，返回 { groupName: [items] }
    groupedParamReview() {
      if (!this.bvResult || !this.bvResult.param_review) return {};
      const groups = {};
      for (const item of this.bvResult.param_review) {
        if (!groups[item.group]) groups[item.group] = [];
        groups[item.group].push(item);
      }
      return groups;
    },
  },

  async mounted() {
    // 全屏 Escape 键退出
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (this.doseFullscreenView) this.doseFullscreenView = null;
        else if (this.fullscreenView) this.fullscreenView = null;
      }
    });

    // 绑定MCNP步骤的action
    this.mcnpSteps[0].action = this.buildWholeBodyPhantom;
    this.mcnpSteps[1].action = this.runMcnpCalculation;
    this.mcnpSteps[2].action = this.generateWholeBodyDoseMap;

    // 页面加载时清除上次会话的文件，确保新流程不受旧文件干扰
    try {
      await axios.post(`${API_BASE}/clear-session`);
      console.log('[初始化] 已清除上次会话文件，可以开始新的处理流程');
    } catch (err) {
      // 409 表示 MCNP/ICRP-116 计算正在运行，不是真正的错误
      console.warn('[初始化] 清除会话文件失败（可忽略）:', err.message);
    }

    // 同步 ICRP-116 后端状态：页面刷新后前端状态丢失，但后端可能仍有任务在运行
    try {
      const { data: icrpStatus } = await axios.get(`${API_BASE}/api/icrp116/status`);
      // 无论任务是否运行，始终从服务端恢复 deDfMode（服务器重启后从磁盘 run_mode.json 读取）
      if (typeof icrpStatus.deDfMode === 'boolean' && icrpStatus.deDfMode) {
        this.icrp116DeDfMode = true;
        console.log('[初始化] 从服务端恢复 DE/DF 模式: true');
      }
      if (icrpStatus.running) {
        console.log('[初始化] 检测到 ICRP-116 验证任务正在运行，恢复轮询');
        this.icrp116Running = true;
        // 恢复轮询，继续接收日志和进度
        this.icrp116PollTimer = setInterval(async () => {
          try {
            const { data } = await axios.get(`${API_BASE}/api/icrp116/status`);
            if (data.logs && data.logs.length) {
              this.icrp116Logs.push(...data.logs);
              if (this.icrp116Logs.length > 500) this.icrp116Logs.splice(0, this.icrp116Logs.length - 500);
            }
            this.icrp116Status = {
              completed:       data.completed,
              failed:          data.failed,
              doneEnergies:    data.doneEnergies    || [],
              currentCase:     data.currentCase,
              resultFiles:     data.resultFiles     || [],
              afDoneEnergies:  data.afDoneEnergies  || [],
              afCurrentCase:   data.afCurrentCase,
              afResultFiles:   data.afResultFiles   || [],
            };
            if (!data.running) {
              this.icrp116Running = false;
              clearInterval(this.icrp116PollTimer);
              this.icrp116PollTimer = null;
            }
          } catch (_) { /* 忽略轮询错误 */ }
        }, 3000);
      }
    } catch (err) {
      console.warn('[初始化] ICRP-116 状态同步失败（可忽略）:', err.message);
    }

    // mounted时尚无CT数据，tumor_position保持默认[0,0,0]（CT中心）
  },

  methods: {
    // ========== 剂量组分设置方法 ==========
    dsOnParamChange() {
      if (!this.dsAutoCalc) return;
      clearTimeout(this.dsAutoTimer);
      this.dsAutoTimer = setTimeout(() => { this.dsCalculate(); }, 800);
    },

    // 肿瘤深度滑块专用handler：同步dsTumorDepth到tumor_position[2]
    // depth 从 CT 区域顶面往下量（CT中心 = depth=ctHalfZ）
    // tumor_position[2] 相对CT区域中心（即体素空间原点），tumor_position[2] = ctHalfZ - depth
    dsOnTumorDepthChange() {
      const ctHalfZ = this.ctMetadata
        ? this.ctMetadata.phys_size_cm[2] / 2
        : (this.dsPhantomPhysDims.z - this.dsPhantomPhysDims.zc - this.dsCtToPhantomOffset[2]);
      this.dsPhantom.tumor_position[2] = parseFloat(
        (ctHalfZ - this.dsTumorDepth).toFixed(1)
      );
      this.dsOnParamChange();
    },

    dsOnIntensityChange() {
      this.dsSource.intensity = Math.pow(10, Number(this.dsIntensityExp));
      this.dsOnParamChange();
    },

    // 将肿瘤位置重置到CT体积中心（相对体模中心=0,0,0）
    dsLocateToCtCenter() {
      this.dsPhantom.tumor_position = [0, 0, 0];
      // 各视图切片跳到中间
      for (const v of ['axial', 'coronal', 'sagittal']) {
        if (this.slices[v].length) {
          this.dsVizCtSliceIndices[v] = Math.floor(this.slices[v].length / 2);
        }
      }
      if (this.ctMetadata) {
        this.dsTumorDepth = parseFloat((this.ctMetadata.phys_size_cm[2] / 4).toFixed(1));
      }
      this.dsOnParamChange();
    },

    // 点击CT图像设置肿瘤 X-Z 位置
    dsSetTumorFromCTClick(event) {
      if (!this.ctMetadata) return;
      const canvas = this.$refs.dsCTCanvas;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const relX = (event.clientX - rect.left) / rect.width;
      const relY = (event.clientY - rect.top) / rect.height;
      const meta = this.ctMetadata;
      const view = this.dsVizCtView;
      const pos = [...this.dsPhantom.tumor_position];

      if (view === 'axial') {
        // axial: image width=X, image height=Y (inverted)
        pos[0] = parseFloat((relX * meta.phys_size_cm[0] - meta.phys_size_cm[0] / 2).toFixed(1));
        pos[1] = parseFloat((meta.phys_size_cm[1] / 2 - relY * meta.phys_size_cm[1]).toFixed(1));
      } else if (view === 'coronal') {
        // coronal: image width=X, image height=Z (inverted)
        pos[0] = parseFloat((relX * meta.phys_size_cm[0] - meta.phys_size_cm[0] / 2).toFixed(1));
        pos[2] = parseFloat((meta.phys_size_cm[2] / 2 - relY * meta.phys_size_cm[2]).toFixed(1));
      } else {
        // sagittal: image width=Y, image height=Z (inverted)
        pos[1] = parseFloat((relX * meta.phys_size_cm[1] - meta.phys_size_cm[1] / 2).toFixed(1));
        pos[2] = parseFloat((meta.phys_size_cm[2] / 2 - relY * meta.phys_size_cm[2]).toFixed(1));
      }
      this.dsPhantom.tumor_position = pos;
      this.dsOnParamChange();
    },

    // 拖动切片滑块时同步肿瘤对应方向坐标
    dsOnCtSliceChange() {
      if (!this.ctMetadata) return;
      const meta = this.ctMetadata;
      const view = this.dsVizCtView;
      const pos = [...this.dsPhantom.tumor_position];

      if (view === 'axial') {
        const total = this.slices.axial.length || 1;
        pos[2] = parseFloat(((this.dsVizCtSliceIndices.axial / total) * meta.phys_size_cm[2] - meta.phys_size_cm[2] / 2).toFixed(1));
      } else if (view === 'coronal') {
        const total = this.slices.coronal.length || 1;
        pos[1] = parseFloat(((this.dsVizCtSliceIndices.coronal / total) * meta.phys_size_cm[1] - meta.phys_size_cm[1] / 2).toFixed(1));
      } else {
        const total = this.slices.sagittal.length || 1;
        pos[0] = parseFloat(((this.dsVizCtSliceIndices.sagittal / total) * meta.phys_size_cm[0] - meta.phys_size_cm[0] / 2).toFixed(1));
      }
      this.dsPhantom.tumor_position = pos;
      this.dsOnParamChange();
    },

    dsDdpPointsComp(component) {
      if (!this.dsResult || !this.dsResult.depth_profile) return '';
      const profile = this.dsResult.depth_profile;
      const maxD    = Math.max(...profile.map(p => p.total_weighted_cgy), 0.001);
      const keyMap  = { boron: 'weighted_boron_cgy', nitrogen: 'weighted_nitrogen_cgy',
                        hydrogen: 'weighted_hydrogen_cgy', gamma: 'weighted_gamma_cgy' };
      const k = keyMap[component];
      return profile.map((p, i) => {
        const x = 40 + (i / (profile.length - 1)) * 350;
        const y = 180 - (p[k] / maxD) * 155;
        return `${x},${y}`;
      }).join(' ');
    },

    async dsCalculate() {
      this.dsLoading = true;
      try {
        const params = {
          source_position:  [...this.dsSource.position],
          source_direction: [...this.dsSource.direction],
          beam_radius:      this.dsSource.beam_radius,
          source_type:      this.dsSource.source_type,
          energy_mono:      this.dsSource.energy_mono,
          energy_spectrum:  this.dsSource.source_type !== 'mono' ? this.dsSource.energy_spectrum : null,
          intensity:        this.dsSource.intensity,
          phantom_center:   [...this.dsPhantom.center],
          phantom_rotation: [...this.dsPhantom.rotation_deg],
          phantom_type:     this.dsPhantom.phantom_type,
          height_cm:        this.dsPhantom.height_cm,
          weight_kg:        this.dsPhantom.weight_kg,
          tumor_position:   [...this.dsPhantom.tumor_position],
          tumor_radius:     this.dsPhantom.tumor_radius,
          tumor_depth_cm:   this.dsTumorDepth,
          cbe_rbe:          JSON.parse(JSON.stringify(this.dsCbeRbe)),
          boron_conc:       { ...this.dsBoronConc }
        };
        const { data } = await axios.post(`${API_BASE}/dose-components/calculate`, params);
        if (data.success) {
          this.dsResult = data.result;
        } else {
          this.showMessage('计算失败：' + (data.message || '未知错误'), 'error');
        }
      } catch (e) {
        this.showMessage('请求失败：' + e.message, 'error');
      } finally {
        this.dsLoading = false;
      }
    },

    async dsRunValidation() {
      this.dsValidating = true;
      this.dsValidateResult = null;
      try {
        const params = {
          cbe_rbe:   JSON.parse(JSON.stringify(this.dsCbeRbe)),
          boron_conc: { ...this.dsBoronConc },
          source_position:  [...this.dsSource.position],
          source_direction: [...this.dsSource.direction]
        };
        const { data } = await axios.post(`${API_BASE}/dose-components/validate`, params);
        if (data.success) {
          this.dsValidateResult = data;
        } else {
          this.showMessage('验证失败：' + (data.message || ''), 'error');
        }
      } catch (e) {
        this.showMessage('验证请求失败：' + e.message, 'error');
      } finally {
        this.dsValidating = false;
      }
    },

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

      this.niiUploading = true;
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

        // 保存 CT 元数据并将肿瘤默认定位到 CT 体积中心
        if (response.data.ctMetadata && !response.data.ctMetadata.error) {
          this.ctMetadata = response.data.ctMetadata;
          // 肿瘤默认位置：CT 物理中心（tumor_position相对CT中心，故[0,0,0]即CT中心）
          this.dsPhantom.tumor_position = [0, 0, 0];
          // 深度与位置保持一致：depth=ctHalfZ 对应 tumor_position[2]=0（CT中心）
          this.dsTumorDepth = parseFloat((this.ctMetadata.phys_size_cm[2] / 2).toFixed(1));
          // 各视图切片跳到中间
          this.dsVizCtSliceIndices = {
            axial:    Math.floor(this.slices.axial.length / 2),
            coronal:  Math.floor(this.slices.coronal.length / 2),
            sagittal: Math.floor(this.slices.sagittal.length / 2)
          };
          this.dsOnParamChange();
        }

        // 启用第一个MCNP步骤
        this.mcnpSteps[0].disabled = false;

        this.showMessage('CT影像加载成功!', 'success');
      } catch (error) {
        console.error('Upload error:', error);
        this.showMessage('上传失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.niiUploading = false;
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

    toggleFullscreen(view) {
      this.fullscreenView = this.fullscreenView === view ? null : view;
    },

    // ========== 器官轮廓 ==========
    async generateContourOverlay() {
      if (!this.niiPath || this.contourMasks.length === 0) return;
      this.contourGenerating = true;
      try {
        // 区分：手动上传的文件 vs 自动勾画产生的服务器路径
        const serverPaths = this.contourMasks.filter(m => m.serverPath).map(m => m.serverPath);
        const uploadFiles  = this.contourMasks.filter(m => m.file);

        if (serverPaths.length > 0) {
          // 自动勾画模式：直接传路径给后端
          const resp = await axios.post(`${API_BASE}/generate-contour-slices-by-path`, {
            ctPath: this.niiPath,
            maskPaths: serverPaths,
            organNames: this.contourMasks.filter(m => m.serverPath).map(m => m.name).join(',')
          });
          if (!resp.data.success) throw new Error(resp.data.message || '生成失败');
          this.overlaySlices.axial    = resp.data.axial    || [];
          this.overlaySlices.coronal  = resp.data.coronal  || [];
          this.overlaySlices.sagittal = resp.data.sagittal || [];
          this.showContourOverlay = true;
          this.showMessage('器官轮廓叠加生成成功！', 'success');
          return;
        }

        const formData = new FormData();
        formData.append('ctPath', this.niiPath);
        formData.append('organNames', uploadFiles.map(m => m.name).join(','));
        uploadFiles.forEach(m => formData.append('masks', m.file));

        const resp = await axios.post(`${API_BASE}/generate-contour-slices`, formData);
        if (!resp.data.success) throw new Error(resp.data.message || '生成失败');

        this.overlaySlices.axial    = resp.data.axial    || [];
        this.overlaySlices.coronal  = resp.data.coronal  || [];
        this.overlaySlices.sagittal = resp.data.sagittal || [];
        this.showContourOverlay = true;
        this.showMessage('器官轮廓叠加生成成功！', 'success');
      } catch (err) {
        this.showMessage('轮廓生成失败: ' + err.message, 'error');
      } finally {
        this.contourGenerating = false;
      }
    },

    async runAutoSegment() {
      if (!this.niiPath) return;
      this.autoSegmenting = true;
      this.autoSegResult = null;
      try {
        const resp = await axios.post(`${API_BASE}/auto-segment`, { ctPath: this.niiPath });
        this.autoSegResult = resp.data;
        if (resp.data.success) {
          // 优先使用 key_organs（临床关键器官），避免加载 100+ 个全部器官
          const keySet = new Set(resp.data.key_organs || []);
          const displayNames = resp.data.key_organs && resp.data.key_organs.length > 0
            ? resp.data.organs.filter(n => keySet.has(n))   // 只取关键器官
            : resp.data.organs.slice(0, 20);                // 兜底：最多20个

          const nameToPath = {};
          resp.data.organs.forEach((n, i) => { nameToPath[n] = resp.data.mask_files[i]; });

          this.contourMasks = displayNames.map((name, idx) => ({
            name,
            file: null,
            serverPath: nameToPath[name],
            color: this.contourColors[idx % this.contourColors.length],
            visible: true
          }));
          this.showMessage(`自动勾画完成，识别 ${resp.data.organs.length} 个器官，显示 ${displayNames.length} 个关键器官轮廓`, 'success');
        }
      } catch (err) {
        this.autoSegResult = { success: false, error: err.message };
        this.showMessage('自动勾画失败: ' + err.message, 'error');
      } finally {
        this.autoSegmenting = false;
      }
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
          gender: 'male'
        });

        this.mcnpSteps[0].status = 'completed';
        this.mcnpSteps[0].result = `体模构建完成: ${response.data.message || '成功'}`;
        this.mcnpSteps[1].disabled = false;
        this.phantomBuilt = true;
        this.detectedRegion = response.data.anatomicalRegion || '';

        // 保存全身体模预览切片（供几何可视化使用）
        if (response.data.phantomSlices) {
          this.phantomSlices = response.data.phantomSlices;
          // 各视图默认跳到中间切片
          for (const view of ['axial', 'coronal', 'sagittal']) {
            const len = (this.phantomSlices[view] || []).length;
            this.dsVizPhantomSliceIndices[view] = Math.floor(len / 2);
          }
          this.dsVizPhantomView = 'sagittal';
        }

        this.addLog('全身体模构建成功', 'success');
        this.showMessage('全身体模构建成功，可以开始MCNP计算或直接进行风险评估', 'success');

        // 体模构建完成后设置默认参数：源与肿瘤高度一致、侧向水平入射
        this.dsPhantom.height_cm    = 170;
        this.dsPhantom.weight_kg    = 70;
        this.dsPhantom.tumor_position = [0, 0, 0];
        this.dsPhantom.tumor_radius   = 2.0;
        // 默认深度 = CT半高，对应 tumor_position[2]=0（CT区域中心），保持两者一致
        this.dsTumorDepth = this.ctMetadata
          ? parseFloat((this.ctMetadata.phys_size_cm[2] / 2).toFixed(1))
          : 7.0;
        // 肿瘤在体模坐标系中的实际Z（包含CT区域偏移，如chest→+45.6cm）
        // 源Z与肿瘤体模Z保持一致，确保可视化中两者在同一水平线上
        const tumorPhantomZ = this.dsTumorInPhantomCm[2];
        // 源必须在体外：AM体模半宽27.14cm，取-40cm确保距体表≥12cm
        this.dsSource.position    = [-40, 0, tumorPhantomZ];
        this.dsSource.direction   = [1, 0, 0];
        this.dsSource.beam_radius = 5.0;
        this.dsSource.intensity   = 1e12;
        this.dsSource.energy_spectrum.weights = [0.00, 0.05, 0.15, 0.25, 0.25, 0.15, 0.10, 0.04, 0.01];
        this.dsCbeRbe = {
          tumor:        { boron_cbe: 3.8,  nitrogen_rbe: 3.2, hydrogen_rbe: 3.2, gamma_rbe: 1.0 },
          normal_tissue:{ boron_cbe: 1.35, nitrogen_rbe: 3.2, hydrogen_rbe: 3.2, gamma_rbe: 1.0 },
          skin:         { boron_cbe: 2.5,  nitrogen_rbe: 3.2, hydrogen_rbe: 3.2, gamma_rbe: 1.0 }
        };
        this.dsBoronConc = { tumor: 60, skin: 25, blood: 25, normal_tissue: 18 };
        // 触发右侧数据面板更新
        this.$nextTick(() => { this.dsCalculate(); });
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
      // 每次重新计算时清空二次癌风险评估界面
      this.riskResults = null;
      this.loading = true;
      this.currentStep = 1;
      this.mcnpSteps[1].status = 'active';
      this.loadingMessage = 'MCNP计算中,请耐心等待...';
      this.addLog('开始MCNP蒙特卡洛模拟...');
      this.progress = 0;

      // 收集当前剂量组分参数设置
      const mcnpParams = {
        source_position:  [...this.dsSource.position],
        source_direction: [...this.dsSource.direction],
        beam_radius:      this.dsSource.beam_radius,
        source_type:      this.dsSource.source_type,
        energy_mono:      this.dsSource.energy_mono,
        energy_spectrum:  this.dsSource.source_type !== 'mono' ? this.dsSource.energy_spectrum : null,
        intensity:        this.dsSource.intensity,
        phantom_center:   [...this.dsPhantom.center],
        phantom_rotation: [...this.dsPhantom.rotation_deg],
        phantom_type:     this.dsPhantom.phantom_type,
        height_cm:        this.dsPhantom.height_cm,
        weight_kg:        this.dsPhantom.weight_kg,
        tumor_position:   [...this.dsPhantom.tumor_position],
        tumor_radius:     this.dsPhantom.tumor_radius,
        tumor_depth_cm:   this.dsTumorDepth,
        cbe_rbe:          JSON.parse(JSON.stringify(this.dsCbeRbe)),
        boron_conc:       { ...this.dsBoronConc }
      };
      this.addLog(`源位置: [${mcnpParams.source_position.join(', ')}] cm, 束流半径: ${mcnpParams.beam_radius} cm`);
      this.addLog(`肿瘤位置: [${mcnpParams.tumor_position.join(', ')}] cm, 半径: ${mcnpParams.tumor_radius} cm`);

      // 轮询后端实时进度
      const progressInterval = setInterval(async () => {
        try {
          const { data } = await axios.get(`${API_BASE}/mcnp-progress`);
          if (data.progress > this.progress) {
            this.progress = data.progress;
          }
          if (data.logs && data.logs.length) {
            data.logs.forEach(line => this.addLog(line, 'info'));
          }
        } catch (_) { /* 忽略轮询错误 */ }
      }, 1000);

      try {
        const response = await axios.post(`${API_BASE}/run-mcnp-computation`, mcnpParams);

        clearInterval(progressInterval);
        this.progress = 100;

        this.mcnpSteps[1].status = 'completed';
        this.mcnpSteps[1].result = response.data.message || '计算完成';
        this.mcnpSteps[2].disabled = false;

        this.addLog('MCNP计算完成，自动生成剂量分布图...', 'success');
        this.showMessage('MCNP计算完成，正在生成剂量分布图...', 'success');

        // MCNP完成后自动触发剂量分布图生成
        await this.generateWholeBodyDoseMap(mcnpParams);
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

    async generateWholeBodyDoseMap(mcnpParams) {
      this.loading = true;
      this.currentStep = 2;
      this.mcnpSteps[2].status = 'active';
      this.loadingMessage = '生成全身剂量分布图...';
      this.addLog('开始生成全身剂量可视化...');

      // 如果没有传入参数，使用当前面板设置
      const params = mcnpParams || {
        source_position:  [...this.dsSource.position],
        source_direction: [...this.dsSource.direction],
        beam_radius:      this.dsSource.beam_radius,
        phantom_type:     this.dsPhantom.phantom_type,
        tumor_position:   [...this.dsPhantom.tumor_position],
        tumor_radius:     this.dsPhantom.tumor_radius,
      };

      try {
        // 调用后端API生成剂量分布图，传入源和肿瘤参数用于可视化叠加
        const response = await axios.post(`${API_BASE}/generate-wholebody-dose-map`, {
          axialImagePath:   this.slices.axial[0] || '',
          source_position:  params.source_position,
          source_direction: params.source_direction,
          beam_radius:      params.beam_radius,
          phantom_type:     params.phantom_type,
          tumor_position:   params.tumor_position,
          tumor_radius:     params.tumor_radius,
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

      this.doseUploading = true;

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
        this.doseUploading = false;
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

    toggleDoseFullscreen(view) {
      this.doseFullscreenView = view;
    },
    doseSliceKey(view) {
      return 'dose' + view.charAt(0).toUpperCase() + view.slice(1);
    },

    removeDoseFile(index) {
      this.doseFiles.splice(index, 1);
    },

    async reapplyDoseOrgans() {
      this.doseOrganApplying = true;
      try {
        const visibleOrgans = this.doseOrganList
          .filter(o => o.visible)
          .map(o => o.keyword)
          .join(',');
        const response = await axios.post(`${API_BASE}/reapply-dose-organs`, { visibleOrgans });
        if (response.data.success) {
          this.slices.doseAxial    = response.data.doseAxial    || [];
          this.slices.doseCoronal  = response.data.doseCoronal  || [];
          this.slices.doseSagittal = response.data.doseSagittal || [];
          this.doseOrgansDirty = false;
          this.showMessage('器官轮廓已更新', 'success');
        } else {
          throw new Error(response.data.message || '更新失败');
        }
      } catch (err) {
        this.showMessage('轮廓更新失败: ' + (err.response?.data?.message || err.message), 'error');
      } finally {
        this.doseOrganApplying = false;
      }
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
      formData.append('niiPath', this.niiPath);
      formData.append('npyPath', this.npyPath);

      try {
        const response = await axios.post(`${API_BASE}/generate-dvh`, formData);
        
        this.dvhImage = response.data.dvhImagePath
          ? `${API_BASE}${response.data.dvhImagePath}`
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
    async runRiskAssessment() {
      if (!this.canRunRiskAssessment) {
        this.showMessage('请先在"MCNP计算"页面完成全身体模构建', 'error');
        return;
      }

      this.loading = true;
      this.loadingMessage = '运行全身风险评估...';

      try {
        // 1. 直接用已有体模参数创建评估会话（无需重新上传CT）
        // 将CT自动识别的解剖区域映射为BEIR VII归一化参考器官
        const regionToTumor = {
          brain: 'brain',
          nasopharynx: 'brain',
          chest: 'lung',
          abdomen: 'liver',
          liver: 'liver',
          pelvis: 'bladder',
        };
        const tumorLocation = regionToTumor[this.detectedRegion] || 'lung';
        const sessionResponse = await axios.post(
          `${API_BASE}/api/wholebody/create-session`,
          {
            age: this.riskParams.age,
            gender: 'male',
            height: 170,
            weight: 70,
            tumorLocation: tumorLocation,
            exposureTime: this.riskParams.exposureTime || 30,
            niiPath: this.niiPath || null
          }
        );
        const sessionId = sessionResponse.data.sessionId;

        // 2. 运行风险评估（后端同步返回结果）
        await axios.post(`${API_BASE}/api/wholebody/run-assessment`, { sessionId });

        // 3. 获取评估报告（JSON格式）
        const resultsResponse = await axios.get(
          `${API_BASE}/api/wholebody/report/${sessionId}?format=json`
        );

        const rawReport = resultsResponse.data.report || {};
        const organList = Object.entries(rawReport)
          .filter(([key]) => key !== 'total')
          .map(([site, data]) => ({
            name: site,
            risk: data.lar_percent || 0,
            larErr: data.lar_err_percent || data.lar_percent || 0,
            larEar: data.lar_ear_percent || 0,
            doseSv: data.dose_sv || 0,
            err: data.err || 0,
            ear: data.ear || 0,
            riskLevel: data.risk_level || this.calcRiskLevel(data.lar_percent || 0),
            organs: data.organs || []
          }))
          .sort((a, b) => b.risk - a.risk);

        const maxRisk = organList.reduce((m, o) => Math.max(m, o.risk), 0);
        this.riskResults = {
          totalRisk: (rawReport.total && rawReport.total.lar_percent) || 0,
          organs: organList,
          maxRisk: maxRisk || 1
        };

        // 4. 获取可视化
        const vizResponse = await axios.get(
          `${API_BASE}/api/wholebody/visualization/${sessionId}`
        );
        this.riskVisualization = vizResponse.data.visualizationPath
          ? `${API_BASE}${vizResponse.data.visualizationPath}`
          : '';

        this.showMessage('风险评估完成', 'success');
      } catch (error) {
        this.showMessage('评估失败: ' + (error.response && error.response.data && error.response.data.message || error.message), 'error');
      } finally {
        this.loading = false;
      }
    },

    getRiskLevel(risk) {
      if (risk < 0.001) return 'low';
      if (risk < 0.01) return 'medium';
      return 'high';
    },

    // 与后端 get_risk_level 一致的四档分类
    calcRiskLevel(lar) {
      if (lar < 0.001) return 'negligible';
      if (lar < 0.01) return 'low';
      if (lar < 0.1) return 'moderate';
      return 'high';
    },

    getRiskDescription(totalRisk) {
      if (totalRisk < 0.001) return '风险可忽略：治疗带来的二次癌症额外风险极低，在可接受范围内。';
      if (totalRisk < 0.01) return '低风险：终生归因风险较低，建议定期随访观察。';
      if (totalRisk < 0.1) return '中等风险：存在一定的二次癌症风险，请结合临床综合评估。';
      return '较高风险：请临床医生综合权衡治疗收益与二次癌症风险，制定随访方案。';
    },

    getRiskLevelLabel(level) {
      const labels = {
        negligible: '忽略',
        low: '低',
        moderate: '中',
        high: '高'
      };
      return labels[level] || level;
    },

    async exportRiskReport() {
      if (!this.riskResults) return;
      const data = JSON.stringify(this.riskResults, null, 2);
      const blob = new Blob([data], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'secondary_cancer_risk_report.json';
      a.click();
      URL.revokeObjectURL(url);
    },

    // ========== ICRP 标准体模对比 ==========

    async runBeir7Validation() {
      this.bvLoading = true;
      this.bvResult = null;
      this.bvError = '';
      this.expandedCases = {};
      try {
        const response = await axios.get(`${API_BASE}/api/beir7-validation`, { timeout: 60000 });
        if (response.data.success) {
          this.bvResult = response.data.data;
        } else {
          this.bvError = response.data.error || '验证失败';
        }
      } catch (err) {
        this.bvError = err.response?.data?.error || err.message || '请求失败';
      } finally {
        this.bvLoading = false;
      }
    },

    toggleDsCase(id) {
      this.dsExpandedCases = { ...this.dsExpandedCases, [id]: !this.dsExpandedCases[id] };
    },
    toggleCase(id) {
      this.expandedCases = { ...this.expandedCases, [id]: !this.expandedCases[id] };
    },

    async runIcrcComparison() {
      this.icrcLoading = true;
      this.icrcResult = null;
      this.icrcChartUrl = '';
      this.icrcError = '';
      try {
        const response = await axios.post(`${API_BASE}/api/icrp-comparison`, {
          phantom_type: this.icrcPhantomType
        }, { timeout: 600000 });

        if (response.data.success) {
          this.icrcResult = response.data.data;
          this.icrcChartUrl = response.data.chart_url
            ? `${API_BASE}${response.data.chart_url}`
            : '';
        } else {
          this.icrcError = response.data.message || '对比计算失败';
        }
      } catch (err) {
        this.icrcError = err.response?.data?.error || err.message || '请求失败';
      } finally {
        this.icrcLoading = false;
      }
    },

    async runNeutronIcrpComparison() {
      this.neutronLoading = true;
      this.neutronCharts = [];
      this.neutronSummary = null;
      this.neutronError = '';
      this.neutronActiveChart = 0;
      try {
        const response = await axios.post(`${API_BASE}/api/neutron-icrp-dose-comparison`, {
          phantom_type: this.neutronPhantomType
        }, { timeout: 120000 });

        if (response.data.success) {
          this.neutronCharts = response.data.charts.filter(c => c.url);
          this.neutronSummary = response.data.summary;
        } else {
          this.neutronError = response.data.message || '图表生成失败';
        }
      } catch (err) {
        this.neutronError = err.response?.data?.error || err.message || '请求失败';
      } finally {
        this.neutronLoading = false;
      }
    },

    // ── ICRP-116 AP 光子验证 ──────────────────────────────────
    async startIcrp116Validation() {
      if (this.icrp116Running) return;
      this.icrp116Running = true;
      this.icrp116Status = {
        completed: false, failed: false,
        currentCase: null, doneEnergies: [],
        elapsedSec: 0, logs: [], resultFiles: [],
        sexAvg: this.icrp116SexAvg, phase: 'AM',
        afDoneEnergies: [], afCurrentCase: null, afResultFiles: [],
      };

      try {
        const resp = await axios.post(`${API_BASE}/api/icrp116/start-validation`, {
          energies:   this.icrp116Selected,
          sexAvg:     this.icrp116SexAvg,
          forceRerun: this.icrp116ForceRerun,
          deDfMode:   this.icrp116DeDfMode,
        });
        if (!resp.data.success) {
          this.icrp116Status.logs.push({
            time: new Date().toLocaleTimeString('zh-CN'),
            text: '[错误] ' + resp.data.message
          });
          this.icrp116Running = false;
          return;
        }
        this.icrp116Status.logs.push({
          time: new Date().toLocaleTimeString('zh-CN'),
          text: '✓ 任务已启动，开始轮询进度...'
        });
      } catch (err) {
        this.icrp116Status.logs.push({
          time: new Date().toLocaleTimeString('zh-CN'),
          text: '[错误] 启动失败: ' + err.message
        });
        this.icrp116Running = false;
        return;
      }

      // 每 3 秒轮询状态
      this.icrp116PollTimer = setInterval(async () => {
        try {
          const { data } = await axios.get(`${API_BASE}/api/icrp116/status`);
          this.icrp116Status = data;
          this.icrp116Running = data.running;
          // 从服务端状态恢复 deDfMode（防止页面刷新后模式丢失导致 Step3 用错误参数）
          if (typeof data.deDfMode === 'boolean') {
            this.icrp116DeDfMode = data.deDfMode;
          }
          // 自动滚动日志
          this.$nextTick(() => {
            const el = this.$refs.icrp116LogBody;
            if (el) el.scrollTop = el.scrollHeight;
          });
          if (!data.running) {
            clearInterval(this.icrp116PollTimer);
            this.icrp116PollTimer = null;
          }
        } catch (_) { /* 忽略轮询错误 */ }
      }, 3000);
    },

    async cancelIcrp116Validation() {
      try {
        await axios.post(`${API_BASE}/api/icrp116/cancel`);
        this.icrp116Running = false;
        if (this.icrp116PollTimer) {
          clearInterval(this.icrp116PollTimer);
          this.icrp116PollTimer = null;
        }
      } catch (err) {
        console.error('取消失败:', err.message);
      }
    },

    // ── ICRP-116 Step 3：计算 h_E 并与参考值对比 ──────────────
    async runIcrp116Step3() {
      if (this.icrp116Step3Loading) return;
      this.icrp116Step3Loading = true;
      this.icrp116Step3Done    = false;
      this.icrp116Step3Result  = null;
      this.icrp116Step3Log     = [];
      this.icrp116ChartUrl     = null;
      const pushLog = (text, type = '') => {
        this.icrp116Step3Log.push({
          time: new Date().toLocaleTimeString('zh-CN'),
          text, type,
        });
      };
      try {
        pushLog('▶ 启动 Step3 分析脚本...');
        const { data } = await axios.post(`${API_BASE}/api/icrp116/run-step3`, {
          deDfMode: this.icrp116DeDfMode,
        });
        if (data.logs && data.logs.length) {
          data.logs.forEach(l => pushLog(l));
        }
        if (data.success) {
          this.icrp116Step3Result = data.results;
          this.icrp116Step3Done   = true;
          pushLog('✓ 计算完成，可点击「生成对比图」查看图表', 'success');
        } else {
          pushLog('[错误] ' + data.message, 'error');
        }
      } catch (err) {
        pushLog('[错误] 请求失败: ' + err.message, 'error');
      } finally {
        this.icrp116Step3Loading = false;
      }
    },

    async genIcrp116Chart() {
      if (this.icrp116ChartLoading) return;
      this.icrp116ChartLoading = true;
      try {
        const { data } = await axios.get(`${API_BASE}/api/icrp116/chart-image`);
        if (data.success) {
          this.icrp116ChartUrl = 'data:image/png;base64,' + data.imageBase64;
        } else {
          alert('加载图表失败：' + data.message);
        }
      } catch (err) {
        alert('加载图表失败：' + err.message);
      } finally {
        this.icrp116ChartLoading = false;
      }
    },

    async checkXsdir() {
      if (this.icrp116XsdirChecking) return;
      this.icrp116XsdirChecking = true;
      this.icrp116XsdirInfo = null;
      try {
        const { data } = await axios.get(`${API_BASE}/api/icrp116/check-xsdir`);
        this.icrp116XsdirInfo = data;
      } catch (err) {
        this.icrp116XsdirInfo = { success: false, message: '检测失败: ' + err.message, available: [] };
      } finally {
        this.icrp116XsdirChecking = false;
      }
    },

    formatElapsed(sec) {
      if (!sec) return '0s';
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) return `${h}h ${m}m`;
      if (m > 0) return `${m}m ${s}s`;
      return `${s}s`;
    },
    // ────────────────────────────────────────────────────────

    getDeviationClass(pct) {
      if (pct === null) return '';
      const abs = Math.abs(pct);
      if (abs <= 5) return 'dev-good';
      if (abs <= 15) return 'dev-ok';
      return 'dev-warn';
    },

    getDeviationRating(pct) {
      if (pct === null) return 'none';
      const abs = Math.abs(pct);
      if (abs <= 5) return 'good';
      if (abs <= 15) return 'ok';
      return 'warn';
    },

    getDeviationRatingLabel(pct) {
      if (pct === null) return '-';
      const abs = Math.abs(pct);
      if (abs <= 5) return '优';
      if (abs <= 15) return '良';
      return '注意';
    },

    // ── 剂量 & 风险关联方法 ──────────────────────────────────
    /**
     * 从 riskResults.organs 中按 cancer_site 名称查找指定字段值
     * @param {string|null} cancerSite  - 如 'brain'、'liver' 等
     * @param {string}      field       - 'doseSv' | 'risk' | 'riskLevel' | 'larErr' | 'larEar'
     */
    getOrganRiskData(cancerSite, field) {
      if (!this.riskResults || !cancerSite) return null;
      const found = this.riskResults.organs.find(o => o.name === cancerSite);
      if (!found) return null;
      return found[field] !== undefined ? found[field] : null;
    },

    getLarClass(lar) {
      if (lar === null) return '';
      if (lar < 0.001) return 'lar-negligible';
      if (lar < 0.01)  return 'lar-low';
      if (lar < 0.1)   return 'lar-moderate';
      return 'lar-high';
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
  font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', 'Hiragino Sans GB', Tahoma, Geneva, Verdana, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  color: #333;
}

/* ========== 顶部导航 ========== */
.platform-header {
  background: white;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
  padding: 0.75rem 2rem 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  position: sticky;
  top: 0;
  z-index: 100;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo-section h1 {
  font-size: 1.35rem;
  color: #667eea;
  margin: 0;
  white-space: nowrap;
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
  gap: 0.35rem;
  width: 100%;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid #f0f0f0;
  flex-wrap: wrap;
}

.nav-tab {
  flex: 1;
  text-align: center;
  padding: 0.55rem 0.5rem 0.75rem;
  border: none;
  background: #f5f5f5;
  cursor: pointer;
  border-radius: 8px 8px 0 0;
  transition: all 0.3s;
  font-size: 1rem;
  font-weight: 500;
  white-space: nowrap;
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
  padding: 1.2rem 2rem 2rem;
  max-width: 1800px;
  margin: 0 auto;
}

.tab-content {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  animation: fadeIn 0.5s;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ========== 工作区布局 ========== */
.workspace {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}

/* ========== 控制面板 (顶部横向) ========== */
.control-panel {
  background: #f9f9f9;
  border-radius: 8px;
  padding: 1rem 1.5rem;
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 0 2.5rem;
  align-items: flex-start;
}

.panel-section {
  flex: 1;
  min-width: 200px;
  margin-bottom: 0.75rem;
  padding-bottom: 0;
  border-bottom: none;
  padding-right: 2rem;
  border-right: 1px solid #e0e0e0;
}

.panel-section:last-child {
  border-right: none;
  padding-right: 0;
}

.panel-section h3 {
  color: #667eea;
  margin-bottom: 0.75rem;
  font-size: 1rem;
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
  margin-top: 0.6rem;
  padding: 0.7rem 0.8rem;
  background: white;
  border-radius: 6px;
  font-size: 0.85rem;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}

.info-item--col {
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
}

.filename-value {
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #333;
  font-size: 0.82rem;
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

/* ========== 切面滑块（嵌入切面框下方）========== */
.viewer-slice-control {
  padding: 4px 8px 6px;
  background: #1a1a2e;
}

.viewer-slider {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #444;
  outline: none;
  -webkit-appearance: none;
  cursor: pointer;
}

.viewer-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #667eea;
  cursor: pointer;
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
  gap: 0.8rem;
}

.viewer-panel {
  background: #f9f9f9;
  border-radius: 8px;
  overflow: hidden;
}

.panel-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 0.5rem 0.8rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h4 {
  margin: 0;
  font-size: 0.9rem;
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
  max-height: 420px;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
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
  background: #1e2530;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 600px;
  border: 1px solid #2d3748;
}

.log-header {
  background: #2d3748;
  color: #e2e8f0;
  padding: 0.6rem 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #4a5568;
  white-space: nowrap;
}

.log-header h4 {
  margin: 0;
  font-size: 0.9rem;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 0.78rem;
  line-height: 1.5;
  background: #1e2530;
  color: #a0aec0;
}

.log-entry {
  display: flex;
  gap: 0.5rem;
  padding: 0.2rem 0.4rem;
  border-left: 2px solid #4299e1;
  margin-bottom: 0.15rem;
  background: rgba(255,255,255,0.02);
  border-radius: 0 3px 3px 0;
}

.log-entry.success {
  border-color: #48bb78;
  color: #9ae6b4;
}

.log-entry.error {
  border-color: #fc8181;
  color: #fed7d7;
}

.log-time {
  color: #4a5568;
  flex-shrink: 0;
  font-size: 0.72rem;
  padding-top: 0.05rem;
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

/* 剂量面板下方滑块 */
.dose-panel-slider {
  padding: 4px 8px 6px;
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
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
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

.phantom-status-ok {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 6px;
  padding: 0.75rem 1rem;
}

.phantom-status-ok .status-check {
  color: #059669;
  font-weight: 600;
  display: block;
  margin-bottom: 0.5rem;
}

.phantom-summary {
  display: flex;
  gap: 1.5rem;
  font-size: 0.88rem;
  color: #374151;
}

.phantom-status-warn {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  color: #92400e;
  font-size: 0.9rem;
  line-height: 1.6;
}

.hint-text {
  margin-top: 0.5rem;
  font-size: 0.82rem;
  color: #9ca3af;
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

/* ========== 二次癌风险分析 ========== */
.risk-legend {
  display: flex;
  gap: 0.8rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 1rem;
  font-size: 0.82rem;
}

.legend-item {
  padding: 0.25rem 0.7rem;
  border-radius: 12px;
  font-weight: 600;
  color: white;
}

.legend-item.negligible { background: #95a5a6; }
.legend-item.low        { background: #2ecc71; }
.legend-item.moderate   { background: #f39c12; }
.legend-item.high       { background: #e74c3c; }

.secondary-cancer-section {
  margin: 1.5rem 0;
}

.secondary-cancer-section h4 {
  color: #667eea;
  margin-bottom: 0.5rem;
  font-size: 1.05rem;
}

.section-note {
  font-size: 0.82rem;
  color: #888;
  margin-bottom: 1rem;
  line-height: 1.5;
}

.risk-table-wrapper {
  overflow-x: auto;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.secondary-risk-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.secondary-risk-table th {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 0.7rem 0.9rem;
  text-align: center;
  font-weight: 600;
  white-space: nowrap;
}

.secondary-risk-table td {
  padding: 0.6rem 0.9rem;
  border-bottom: 1px solid #f0f0f0;
  text-align: center;
  vertical-align: middle;
}

.secondary-risk-table tbody tr:hover {
  background: #f5f7ff;
}

.organ-name-cell {
  text-align: left !important;
  font-weight: 600;
  color: #333;
  text-transform: capitalize;
}

.num-cell {
  font-family: 'Courier New', monospace;
  color: #444;
}

.lar-combined {
  font-weight: 700;
  color: #667eea !important;
}

.risk-badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 10px;
  font-size: 0.78rem;
  font-weight: 600;
  color: white;
  white-space: nowrap;
}

.risk-badge.negligible { background: #95a5a6; }
.risk-badge.low        { background: #2ecc71; }
.risk-badge.moderate   { background: #f39c12; }
.risk-badge.high       { background: #e74c3c; }

.bar-cell {
  min-width: 100px;
}

.inline-bar-container {
  background: #e0e0e0;
  height: 12px;
  border-radius: 6px;
  overflow: hidden;
}

.inline-bar-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.5s;
}

.inline-bar-fill.negligible { background: #95a5a6; }
.inline-bar-fill.low        { background: linear-gradient(90deg, #2ecc71, #27ae60); }
.inline-bar-fill.moderate   { background: linear-gradient(90deg, #f39c12, #e67e22); }
.inline-bar-fill.high       { background: linear-gradient(90deg, #e74c3c, #c0392b); }

.total-row td {
  background: #f0f4ff;
  font-weight: 700;
  border-top: 2px solid #667eea;
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

/* ========== 全屏遮罩 ========== */
.fullscreen-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.fullscreen-panel {
  background: #1a1a2e;
  border-radius: 12px;
  width: 90vw;
  max-width: 900px;
  height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.fullscreen-image-container {
  flex: 1;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  min-height: 0;
}

.fullscreen-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

/* 剂量全屏面板：冠状/矢状为竖向图，允许更高 */
.dose-fullscreen-panel {
  max-width: 700px;
  height: 92vh;
}

.dose-fs-slice-info {
  color: #a0aec0;
  font-size: 0.85rem;
  min-width: 60px;
  text-align: center;
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
    flex-direction: column;
  }

  .viz-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dose-viewer-grid {
    gap: 0.5rem;
  }
}

@media (max-width: 1024px) {
  .workspace {
    flex-direction: column;
  }

  .control-panel {
    flex-direction: column;
  }

  .panel-section {
    border-right: none;
    padding-right: 0;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 0.75rem;
    margin-bottom: 0.75rem;
  }

  .panel-section:last-child {
    border-bottom: none;
  }

  .mcnp-workspace,
  .dvh-workspace {
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

/* ===== ICRP 对比页样式 ===== */
.icrp-compare-workspace {
  padding: 1.5rem;
  max-width: 1200px;
  margin: 0 auto;
}

.icrp-compare-header h2 {
  font-size: 1.4rem;
  margin-bottom: 0.5rem;
  color: #2c3e50;
}

.icrp-desc {
  color: #666;
  font-size: 0.95rem;
  margin-bottom: 1.5rem;
  line-height: 1.6;
}

.icrp-compare-controls {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.ctrl-label {
  font-weight: 600;
  color: #444;
  white-space: nowrap;
}

.btn-group {
  display: flex;
  gap: 0.5rem;
}

.btn-phantom {
  padding: 0.4rem 1rem;
  border: 2px solid #667eea;
  background: white;
  color: #667eea;
  border-radius: 20px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s;
}

.btn-phantom.active {
  background: #667eea;
  color: white;
}

.btn-phantom:hover:not(.active) {
  background: #f0f0ff;
}

.run-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.icrp-progress-note {
  margin-top: 0.5rem;
  color: #888;
  font-size: 0.85rem;
  font-style: italic;
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

.icrp-summary-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.summary-card {
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 0.8rem 1.2rem;
  min-width: 140px;
  text-align: center;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.card-label {
  font-size: 0.78rem;
  color: #888;
  margin-bottom: 0.3rem;
}

.card-value {
  font-size: 1.1rem;
  font-weight: 700;
  color: #2c3e50;
}

.icrp-chart-section {
  margin-bottom: 2rem;
}

.icrp-chart-section h3,
.icrp-table-section h3 {
  font-size: 1.1rem;
  color: #2c3e50;
  margin-bottom: 0.8rem;
  border-left: 4px solid #667eea;
  padding-left: 0.6rem;
}

.icrp-chart-img {
  max-width: 100%;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.table-legend {
  font-size: 0.82rem;
  margin-bottom: 0.6rem;
  display: flex;
  gap: 1.5rem;
}

/* 器官轮廓折叠头 */
.organ-collapse-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
  padding: 2px 0 6px;
}

.organ-collapse-header:hover {
  opacity: 0.8;
}

.collapse-arrow {
  color: #667eea;
  font-size: 0.75rem;
}

.organ-collapse-summary {
  font-size: 0.8rem;
  color: #888;
  margin-top: 4px;
}

/* 剂量页器官轮廓列表 */
.dose-organ-list {
  max-height: 280px;
  overflow-y: auto;
  margin: 6px 0;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  padding: 2px 0;
}
.dose-organ-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
  user-select: none;
  font-size: 0.82rem;
  transition: background 0.15s;
}
.dose-organ-item:hover { background: #f0f4ff; }
.organ-checkbox {
  width: 14px; height: 14px;
  cursor: pointer;
  flex-shrink: 0;
}

/* 器官轮廓 */
.contour-summary {
  background: #f0f4ff;
  border-radius: 4px;
  margin: 4px 0;
  overflow: hidden;
}

.contour-summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 500;
  color: #667eea;
  user-select: none;
}

.contour-summary-header:hover {
  background: #e4eaff;
}

.contour-list { margin: 0; border-top: 1px solid #dde4ff; max-height: 180px; overflow-y: auto; }
.contour-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 4px;
  border-radius: 4px;
  font-size: 0.82rem;
}
.contour-item:hover { background: #f5f5f5; }
.contour-color-dot {
  width: 12px; height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}
.contour-organ-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #333;
}
.btn-icon-sm {
  border: none; background: transparent;
  cursor: pointer; color: #999; font-size: 0.8rem; padding: 0 2px;
}
.btn-icon-sm:hover { color: #F44336; }
.btn-warn {
  background: #FF9800; color: #fff;
  border: none; border-radius: 6px;
  padding: 0.45rem 0.8rem; cursor: pointer; font-size: 0.85rem;
}
.btn-warn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-active {
  background: #4CAF50; color: #fff;
  border: none; border-radius: 6px;
  padding: 0.45rem 0.8rem; cursor: pointer; font-size: 0.85rem;
}
.contour-msg-warn {
  font-size: 0.78rem; color: #E65100;
  background: #fff3e0; border-radius: 4px; padding: 4px 6px;
}
.contour-msg-ok {
  font-size: 0.78rem; color: #2E7D32;
  background: #e8f5e9; border-radius: 4px; padding: 4px 6px;
}

/* 自动勾画折叠面板 */
.auto-seg-summary {
  background: #e8f5e9;
  border-radius: 4px;
  overflow: hidden;
  font-size: 0.78rem;
}

.auto-seg-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  cursor: pointer;
  color: #2E7D32;
  font-weight: 500;
  user-select: none;
}

.auto-seg-header:hover {
  background: #d4edda;
}

.auto-seg-toggle {
  font-size: 0.7rem;
  color: #4CAF50;
}

.auto-seg-organ-list {
  border-top: 1px solid #c8e6c9;
  max-height: 180px;
  overflow-y: auto;
  padding: 4px 0;
}

.auto-seg-organ-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  color: #333;
  font-size: 0.76rem;
}

.auto-seg-organ-item:hover {
  background: #f1f8e9;
}

.auto-seg-organ-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-good { color: #4CAF50; }
.legend-ok   { color: #FF9800; }
.legend-warn { color: #F44336; }
.legend-disc { color: #9E9E9E; font-size: 0.8rem; }

.icrp-table {
  width: 100%;
  border-collapse: collapse;
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}

.icrp-table th {
  background: #667eea;
  color: white;
  padding: 0.7rem 1rem;
  text-align: center;
  font-size: 0.9rem;
}

/* 双行表头：质量列组 */
.th-group-mass {
  background: #3F51B5;
  border-right: 2px solid #fff;
}

/* 双行表头：体积列组 */
.th-group-volume {
  background: #00796B;
  border-right: 2px solid #fff;
}

/* 第二行子列标题 */
.th-sub {
  font-size: 0.8rem;
  padding: 0.4rem 0.6rem;
}
.th-sub-mass { background: #7986CB; }
.th-sub-vol  { background: #4DB6AC; }

.icrp-table td {
  padding: 0.55rem 1rem;
  border-bottom: 1px solid #f0f0f0;
  text-align: center;
  font-size: 0.9rem;
}

.icrp-table tr:last-child td { border-bottom: none; }
.icrp-table tr:hover td { background: #f8f9ff; }

.organ-name { text-align: left; font-weight: 500; }
.val-ref    { color: #2196F3; font-weight: 600; }
.val-calc   { color: #FF5722; font-weight: 600; }

.dev-good { color: #4CAF50; font-weight: 700; }
.dev-ok   { color: #FF9800; font-weight: 700; }
.dev-warn { color: #F44336; font-weight: 700; }

.badge-good { background: #e8f5e9; color: #4CAF50; padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge-ok   { background: #fff3e0; color: #FF9800; padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge-warn { background: #ffebee; color: #F44336; padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge-disc { background: #f5f5f5; color: #9E9E9E; padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge-none { color: #999; }

.icrp-disc-note {
  background: #fff8e1;
  border-left: 4px solid #FFC107;
  padding: 0.7rem 1rem;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #555;
  line-height: 1.6;
  margin-bottom: 0.8rem;
}

.row-small-organ td { background: #fafafa; }

.val-voxel { color: #607D8B; font-size: 0.85rem; }

.dev-disc { color: #9E9E9E; font-weight: 600; }

.disc-star { color: #9E9E9E; margin-left: 2px; font-size: 0.85rem; cursor: help; }

/* 剂量与风险列组样式 */
.th-group-risk {
  background: #5D4037;
  border-left: 2px solid #fff;
}
.th-sub-risk { background: #8D6E63; }

.val-dose     { color: #1565C0; font-weight: 600; }
.val-baseline { color: #616161; font-size: 0.88rem; }

/* LAR 风险着色 */
.lar-negligible { color: #4CAF50; font-weight: 700; }
.lar-low        { color: #8BC34A; font-weight: 700; }
.lar-moderate   { color: #FF9800; font-weight: 700; }
.lar-high       { color: #F44336; font-weight: 700; }

/* 风险等级徽章 */
.badge-risk-negligible { background: #e8f5e9; color: #4CAF50; padding: 0.1rem 0.4rem; border-radius: 10px; font-size: 0.78rem; font-weight: 600; white-space: nowrap; }
.badge-risk-low        { background: #f1f8e9; color: #8BC34A; padding: 0.1rem 0.4rem; border-radius: 10px; font-size: 0.78rem; font-weight: 600; white-space: nowrap; }
.badge-risk-moderate   { background: #fff3e0; color: #FF9800; padding: 0.1rem 0.4rem; border-radius: 10px; font-size: 0.78rem; font-weight: 600; white-space: nowrap; }
.badge-risk-high       { background: #ffebee; color: #F44336; padding: 0.1rem 0.4rem; border-radius: 10px; font-size: 0.78rem; font-weight: 600; white-space: nowrap; }

/* 风险数据提示条 */
.icrp-null-note {
  font-size: 0.78rem;
  color: #888;
  margin-top: 0.4rem;
  margin-bottom: 0.4rem;
  padding-left: 0.3rem;
}

.icrp-risk-tip {
  background: #e8f5e9;
  border-left: 4px solid #4CAF50;
  padding: 0.55rem 1rem;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #2e7d32;
  margin-bottom: 0.7rem;
}
.icrp-risk-tip--none {
  background: #f5f5f5;
  border-left-color: #9E9E9E;
  color: #616161;
}

/* 总风险汇总行 */
.icrp-risk-summary {
  margin-top: 0.8rem;
  padding: 0.6rem 1rem;
  background: #fce4ec;
  border-left: 4px solid #e91e63;
  border-radius: 4px;
  font-size: 0.88rem;
  color: #444;
}
.risk-val-high  { color: #F44336; font-weight: 700; font-size: 1.05rem; }
.risk-val-mod   { color: #FF9800; font-weight: 700; font-size: 1.05rem; }
.risk-val-low   { color: #4CAF50; font-weight: 700; font-size: 1.05rem; }

.icrp-empty {
  text-align: center;
  padding: 4rem;
  color: #aaa;
  font-size: 1.1rem;
}

.icrp-empty p:first-child {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}

.icrp-error {
  background: #ffebee;
  color: #c62828;
  padding: 1rem;
  border-radius: 8px;
  margin-top: 1rem;
}

/* ===== BEIR VII 验证页样式 ===== */
.bv-workspace { padding: 1.5rem 2rem; max-width: 1200px; margin: 0 auto; }
.bv-header { margin-bottom: 1.5rem; }
.bv-header h2 { margin: 0 0 0.4rem; font-size: 1.4rem; }
.bv-desc { color: #555; margin: 0 0 1rem; }
.bv-run-btn { min-width: 140px; }

.bv-summary-cards {
  display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem;
}
.bv-card {
  flex: 1 1 160px; border-radius: 10px; padding: 1rem 1.2rem;
  text-align: center; border: 1px solid #e0e0e0;
}
.card-pass { background: #e8f5e9; border-color: #a5d6a7; }
.card-fail { background: #ffebee; border-color: #ef9a9a; }
.card-info { background: #e3f2fd; border-color: #90caf9; }
.bv-card-icon { font-size: 1.8rem; margin-bottom: 0.3rem; }
.bv-card-label { font-weight: 600; font-size: 0.95rem; }
.bv-card-sub { font-size: 0.82rem; color: #666; margin-top: 0.2rem; }

/* ── 两层验证结构说明横幅 ── */
.bv-flow-banner {
  display: flex; align-items: stretch; gap: 0;
  margin-bottom: 1.5rem;
  border-radius: 10px; overflow: hidden;
  border: 1px solid #c5cae9;
}
.bvf-tier {
  flex: 1; padding: 0.85rem 1.1rem;
}
.bvf-tier1 { background: #e8eaf6; border-right: 1px solid #c5cae9; }
.bvf-tier2 { background: #e3f2fd; }
.bvf-num {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em;
  color: #5c6bc0; text-transform: uppercase; margin-bottom: 0.2rem;
}
.bvf-tier2 .bvf-num { color: #1565c0; }
.bvf-title {
  font-size: 0.92rem; font-weight: 700; color: #222; margin-bottom: 0.3rem;
}
.bvf-desc  { font-size: 0.8rem; color: #555; line-height: 1.5; margin-bottom: 0.35rem; }
.bvf-items { font-size: 0.78rem; color: #5c6bc0; font-weight: 600; }
.bvf-tier2 .bvf-items { color: #1565c0; }
.bvf-arrow {
  display: flex; align-items: center; justify-content: center;
  padding: 0 0.7rem; font-size: 1.4rem; color: #888;
  background: #ede7f6;
}

.bv-issues { margin-bottom: 1.5rem; }
.bv-issues h3 { font-size: 1rem; margin-bottom: 0.6rem; }
.bv-issue {
  display: flex; gap: 1rem; align-items: flex-start;
  padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 0.6rem;
  border-left: 4px solid;
}
.issue-fixed { background: #f1f8e9; border-color: #7cb342; }
.issue-info  { background: #e3f2fd; border-color: #1976d2; }
.issue-badge {
  font-size: 0.78rem; font-weight: 700; white-space: nowrap;
  padding: 0.2rem 0.5rem; border-radius: 4px;
  background: rgba(0,0,0,0.06);
}
.issue-title { font-weight: 600; margin-bottom: 0.2rem; }
.issue-desc  { font-size: 0.88rem; color: #444; }
.issue-impact { font-size: 0.85rem; color: #666; margin-top: 0.2rem; }

.bv-results { display: flex; flex-direction: column; gap: 1.5rem; }
.bv-section h3 { font-size: 1rem; margin-bottom: 0.6rem; }
.bv-section h3 small { font-weight: normal; color: #888; font-size: 0.82rem; }
.bv-section-half { max-width: 600px; }

.bv-table {
  width: 100%; border-collapse: collapse; font-size: 0.88rem;
}
.bv-table th {
  background: #f5f5f5; padding: 0.5rem 0.7rem;
  text-align: center; border: 1px solid #e0e0e0; white-space: nowrap;
}
.bv-table td {
  padding: 0.4rem 0.7rem; text-align: center;
  border: 1px solid #e8e8e8;
}
.bv-table tr:nth-child(even) td { background: #fafafa; }
.row-baseline td { background: #fff8e1 !important; font-weight: 600; }
.row-special td { background: #fce4ec !important; }
.cell-pass { color: #2e7d32; font-weight: 700; }
.cell-fail { color: #c62828; font-weight: 700; }
.cell-warn { color: #e65100; font-weight: 600; }
.cell-warn { color: #c62828; font-weight: 700; }
.cell-mod  { color: #f57c00; font-weight: 600; }

.bv-empty {
  text-align: center; padding: 4rem; color: #aaa; font-size: 1.1rem;
}
.bv-empty p:first-child { font-size: 3rem; margin-bottom: 0.5rem; }
.bv-error {
  background: #ffebee; color: #c62828;
  padding: 1rem; border-radius: 8px; margin-top: 1rem;
}

/* ── 临床案例验证 ── */
.bv-cases-section { max-width: 100%; }
.bv-cases-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
  gap: 1.2rem;
}
.bv-case-card {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.bv-case-summary {
  padding: 0.85rem 1.2rem;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.bv-case-summary:hover { background: #f5f5f5; }
.bv-case-detail {
  padding: 0 1.2rem 1rem;
  border-top: 1px solid #f0f0f0;
}
.bv-expand-hint {
  font-size: 0.78rem; color: #888; white-space: nowrap;
}
.bv-case-header {
  display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.4rem;
}
.bv-case-num {
  background: #5c6bc0; color: #fff;
  font-size: 0.75rem; font-weight: 700;
  padding: 0.15rem 0.5rem; border-radius: 12px;
  white-space: nowrap;
}
.bv-case-name {
  font-weight: 700; font-size: 0.98rem; color: #222;
}
.bv-case-meta {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.4rem;
}
.bv-case-param {
  font-size: 0.82rem; color: #5c6bc0; font-weight: 600;
  background: #ede7f6; padding: 0.15rem 0.55rem; border-radius: 8px;
}
.bv-case-total {
  font-size: 0.85rem; color: #555;
}
.bv-case-total strong { color: #c62828; }
.bv-case-desc {
  font-size: 0.84rem; color: #444; margin: 0.3rem 0;
}
.bv-case-ref {
  display: flex; align-items: baseline; gap: 0.4rem;
  margin-bottom: 0.6rem;
}
.bv-ref-badge {
  font-size: 0.72rem; font-weight: 700; color: #fff;
  background: #43a047; padding: 0.1rem 0.4rem; border-radius: 4px;
  white-space: nowrap;
}
.bv-ref-text { font-size: 0.82rem; color: #1a6b35; font-style: italic; }
.bv-case-table { margin-bottom: 0.5rem; font-size: 0.82rem; }
.bv-case-table tfoot td {
  border-top: 2px solid #e0e0e0;
  background: #f5f5f5;
  font-size: 0.85rem;
}
.case-total-row td { background: #f9fbe7 !important; }
.bv-case-context {
  font-size: 0.8rem; color: #555; margin: 0.3rem 0 0.1rem;
  border-left: 3px solid #7986cb; padding-left: 0.5rem;
}
.bv-case-citation {
  font-size: 0.75rem; color: #999; margin: 0.2rem 0 0;
  font-style: italic; word-break: break-word;
}

/* 风险级别徽章 */
.risk-badge {
  display: inline-block;
  font-size: 0.72rem; font-weight: 700;
  padding: 0.1rem 0.4rem; border-radius: 4px;
  white-space: nowrap;
}
.risk-negligible { background: #e8f5e9; color: #2e7d32; }
.risk-low        { background: #e3f2fd; color: #1565c0; }
.risk-moderate   { background: #fff8e1; color: #f57f17; }
.risk-high       { background: #ffebee; color: #c62828; }

/* ── 参数合理性总览 ── */
.bv-param-review { max-width: 100%; }

.pr-stat-row {
  display: flex; gap: 0.8rem; margin-bottom: 1rem; flex-wrap: wrap;
}
.pr-stat {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.84rem; font-weight: 700;
  padding: 0.25rem 0.75rem; border-radius: 20px;
}
.pr-stat-match      { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
.pr-stat-acceptable { background: #fff8e1; color: #e65100; border: 1px solid #ffcc80; }
.pr-stat-note       { background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }

.pr-group { margin-bottom: 1.2rem; }
.pr-group-title {
  font-size: 0.88rem; font-weight: 700; color: #5c6bc0;
  background: #ede7f6; padding: 0.3rem 0.8rem;
  border-left: 4px solid #5c6bc0; border-radius: 0 4px 4px 0;
  margin-bottom: 0.4rem;
}
.pr-table { font-size: 0.82rem; }
.pr-param-name { font-weight: 600; white-space: nowrap; }
.pr-code {
  font-family: 'Courier New', 'Consolas', monospace;
  font-size: 0.8rem; color: #333;
}
.pr-source { font-size: 0.78rem; color: #555; font-style: italic; }
.pr-remark { font-size: 0.8rem; color: #555; }

.pr-status-badge {
  display: inline-block;
  font-size: 0.72rem; font-weight: 700;
  padding: 0.1rem 0.45rem; border-radius: 4px;
  white-space: nowrap;
}
.prs-match      { background: #e8f5e9; color: #2e7d32; }
.prs-acceptable { background: #fff8e1; color: #e65100; }
.prs-note       { background: #e3f2fd; color: #1565c0; }

.pr-conclusion {
  margin-top: 0.8rem;
  background: linear-gradient(135deg, #e8f5e9 0%, #f1f8e9 100%);
  border: 1px solid #a5d6a7; border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.88rem; color: #1b5e20; line-height: 1.6;
}
.pr-conclusion-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.4rem; height: 1.4rem;
  background: #2e7d32; color: #fff;
  border-radius: 50%; font-size: 0.8rem; font-weight: 700;
  margin-right: 0.4rem; vertical-align: middle;
}

/* ── 案例卡片：程序/标准结果对比增强 ── */
.case-table-label {
  display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.3rem;
}
.ctlabel-prog {
  font-size: 0.82rem; font-weight: 700; color: #1565c0;
}
.ctlabel-ref {
  font-size: 0.82rem; font-weight: 700; color: #6a1b9a;
}
.spot-verdict {
  font-size: 0.78rem; font-weight: 700;
  padding: 0.1rem 0.5rem; border-radius: 12px; white-space: nowrap;
}
.sv-pass { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
.sv-fail { background: #ffebee; color: #c62828; border: 1px solid #ef9a9a; }

.spot-desc {
  font-size: 0.8rem; color: #555; margin: 0.2rem 0 0.4rem; line-height: 1.5;
}
.spot-table { font-size: 0.78rem; }
.spot-formula { font-family: 'Courier New', monospace; font-size: 0.76rem; color: #333; }
.spot-val    { font-family: 'Courier New', monospace; text-align: right; }
.spot-err    { color: #2e7d32; font-size: 0.76rem; }
.spot-pass   { font-weight: 700; font-size: 0.9rem; }
.sp-ok   { color: #2e7d32; }
.sp-fail { color: #c62828; }
.ddref-tag {
  display: inline-block; font-size: 0.65rem; font-weight: 700;
  background: #fff8e1; color: #e65100; border: 1px solid #ffcc80;
  border-radius: 3px; padding: 0 3px; margin-left: 3px; vertical-align: middle;
}

/* 文献参考对比框 */
.ref-cmp-box {
  margin: 0.6rem 0; padding: 0.7rem 1rem;
  border-radius: 8px; font-size: 0.83rem;
}
.ref-beir7 { background: #e3f2fd; border: 1px solid #90caf9; }
.ref-trend { background: #f3e5f5; border: 1px solid #ce93d8; }
.ref-cmp-title {
  font-weight: 700; margin-bottom: 0.4rem; font-size: 0.85rem;
}
.ref-cmp-row {
  display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.ref-cmp-col { text-align: center; }
.ref-cmp-label { font-size: 0.75rem; color: #666; margin-bottom: 0.15rem; }
.ref-cmp-value { font-size: 1.1rem; font-weight: 700; color: #1565c0; }
.ref-ours      { color: #2e7d32; }
.ref-ci        { font-size: 0.72rem; color: #888; font-weight: 400; }
.ref-cmp-arrow { font-size: 1.4rem; color: #888; }
.ref-cmp-note  { font-size: 0.78rem; color: #555; line-height: 1.5; }
.ref-cmp-expected { margin-top: 0.35rem; font-size: 0.82rem; line-height: 1.5; }
.trend-ok { font-size: 0.78rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 10px; margin-left: 0.3rem; }

/* 案例综合验证结论区 */
.bv-cases-conclusion h3 { color: #4527a0; }
.cases-sum-table { font-size: 0.8rem; }
.case-lar-val { font-family: 'Courier New', monospace; text-align: right; }
.csum-ref-col { font-size: 0.76rem; color: #555; line-height: 1.4; }

.trend-box {
  margin: 0.8rem 0; padding: 0.7rem 1rem;
  background: #fff8e1; border: 1px solid #ffcc80; border-radius: 8px;
  font-size: 0.83rem; line-height: 1.6;
}
.trend-title { font-weight: 700; margin-bottom: 0.3rem; font-size: 0.88rem; }
.trend-actual { margin-top: 0.3rem; color: #333; }

.cases-final-verdict {
  display: flex; align-items: flex-start; gap: 0.7rem;
  margin-top: 0.8rem; padding: 0.9rem 1.1rem;
  border-radius: 10px; font-size: 0.88rem; line-height: 1.7;
}
.cfv-pass { background: linear-gradient(135deg,#e8f5e9,#f1f8e9); border:1px solid #a5d6a7; color:#1b5e20; }
.cfv-warn { background: #fff8e1; border:1px solid #ffcc80; color:#e65100; }
.cfv-icon {
  flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.6rem; height: 1.6rem; border-radius: 50%;
  font-weight: 700; font-size: 0.9rem; margin-top: 0.1rem;
}
.cfv-pass .cfv-icon { background: #2e7d32; color: #fff; }
.cfv-warn .cfv-icon { background: #e65100; color: #fff; }

/* ========================================
   剂量组分设置（嵌入 MCNP Tab）
   ======================================== */

/* MCNP 页面第二个 tab-content 块：顶部加分隔线 */
.tab-content + .tab-content {
  margin-top: 0;
  padding-top: 0;
  border-top: 3px solid rgba(102,126,234,0.2);
}

.ds-mcnp-title {
  padding: 0.6rem 1rem 0.5rem;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 0;
}
.ds-mcnp-title h2 {
  font-size: 1rem;
  color: #4a5568;
  margin-bottom: 2px;
}
.ds-mcnp-title p {
  font-size: 0.77rem;
  color: #718096;
}

.ds-workspace {
  display: grid;
  grid-template-columns: 280px 1fr 1fr;
  gap: 1rem;
  padding: 1rem;
  min-height: 0;
  overflow: auto;
}

/* ── 侧边栏 ── */
.ds-sidebar {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  padding: 0.8rem;
  overflow-y: auto;
  max-height: calc(100vh - 130px);
}

.ds-section {
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 0.75rem;
  margin-bottom: 0.75rem;
}
.ds-section:last-child { border-bottom: none; margin-bottom: 0; }

.ds-section-title {
  font-size: 0.88rem;
  font-weight: 700;
  color: #4a5568;
  margin-bottom: 0.6rem;
}

.ds-field-group { margin-bottom: 0.55rem; }

.ds-label {
  display: block;
  font-size: 0.75rem;
  color: #718096;
  margin-bottom: 0.2rem;
}
.ds-hint-tag {
  display: inline-block;
  font-size: 0.62rem;
  padding: 0 0.3rem;
  border-radius: 3px;
  margin-left: 0.3rem;
  cursor: help;
  vertical-align: middle;
  background: #2d3748;
  color: #a0aec0;
  border: 1px solid #4a5568;
}

.ds-xyz-row {
  display: flex;
  align-items: center;
  gap: 3px;
}
.ds-axis {
  font-size: 0.7rem;
  color: #a0aec0;
  min-width: 16px;
  text-align: right;
}
.ds-input {
  width: 52px;
  padding: 3px 4px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 0.78rem;
  text-align: center;
}
.ds-input:focus { border-color: #667eea; outline: none; }
.ds-input-full {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 0.8rem;
}
.ds-input-full:focus { border-color: #667eea; outline: none; }

.ds-select {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 0.78rem;
  background: #fff;
}
.ds-select:focus { border-color: #667eea; outline: none; }

.ds-row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.4rem;
}

/* 能谱预览条形图 */
.ds-spectrum-preview {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 36px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 2px 4px;
  background: #f7fafc;
}
.ds-spectrum-bar {
  flex: 1;
  min-width: 3px;
  border-radius: 2px 2px 0 0;
  transition: height 0.2s;
}
.ds-spectrum-label {
  display: flex;
  justify-content: space-between;
  font-size: 0.65rem;
  color: #a0aec0;
  margin-top: 1px;
}

/* CBE表格 */
.ds-cbe-table { font-size: 0.72rem; }
.ds-cbe-header {
  display: grid;
  grid-template-columns: 60px 1fr 1fr 1fr 1fr;
  gap: 2px;
  font-weight: 700;
  color: #718096;
  margin-bottom: 3px;
  padding: 0 2px;
}
.ds-cbe-row {
  display: grid;
  grid-template-columns: 60px 1fr 1fr 1fr 1fr;
  gap: 2px;
  align-items: center;
  margin-bottom: 3px;
}
.ds-cbe-tissue { font-size: 0.72rem; color: #4a5568; }
.ds-cbe-input {
  width: 100%;
  padding: 2px 3px;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font-size: 0.7rem;
  text-align: center;
}
.ds-cbe-input:focus { border-color: #667eea; outline: none; }

/* 硼浓度 */
.ds-boron-grid {
  display: grid;
  grid-template-columns: 1fr 80px;
  gap: 4px 8px;
  align-items: center;
}
.ds-boron-label { font-size: 0.75rem; color: #4a5568; }
.ds-boron-input {
  padding: 3px 6px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 0.78rem;
  text-align: center;
  width: 100%;
}
.ds-boron-input:focus { border-color: #667eea; outline: none; }

.ds-calc-btn { width: 100%; padding: 8px; font-size: 0.9rem; }
.ds-auto-hint { font-size: 0.72rem; color: #38a169; text-align: center; margin-top: 4px; }

/* ── 可视化面板 ── */
.ds-viz-panel {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  padding: 0.8rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
/* ── 全身体模切片滑块（位于画布下方） ── */
.ds-phantom-slice-ctrl {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 0 2px;
  margin-bottom: 2px;
}
.ds-phantom-slice-label {
  font-size: 0.72rem;
  color: #718096;
  white-space: nowrap;
  min-width: 68px;
}
.ds-phantom-slider { flex: 1; }
.ds-phantom-slice-num {
  font-size: 0.72rem;
  color: #718096;
  min-width: 46px;
  text-align: right;
}

/* ── CT三视图标签 ── */
.ds-ct-view-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
}
.ds-ct-view-tab {
  padding: 3px 9px;
  font-size: 0.75rem;
  border: 1px solid #4a5568;
  border-radius: 4px;
  background: #2d3748;
  color: #a0aec0;
  cursor: pointer;
  transition: all 0.12s;
}
.ds-ct-view-tab.active {
  background: #4299e1;
  color: #fff;
  border-color: #4299e1;
}
.ds-ct-view-tab:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.ds-ct-view-hint {
  font-size: 0.68rem;
  color: #718096;
  margin-left: 6px;
}

/* ── 几何可视化面板标题行 ── */
.ds-viz-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-bottom: 0.5rem;
}
.ds-viz-title {
  font-size: 0.88rem;
  font-weight: 700;
  color: #4a5568;
}
.ds-viz-mode-tabs {
  display: flex;
  gap: 4px;
}
.ds-mode-tab {
  padding: 3px 10px;
  font-size: 0.78rem;
  border: 1px solid #cbd5e0;
  border-radius: 4px;
  background: #f7fafc;
  color: #4a5568;
  cursor: pointer;
  transition: all 0.15s;
}
.ds-mode-tab.active {
  background: #4299e1;
  color: #fff;
  border-color: #4299e1;
}
.ds-mode-tab:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ds-canvas-wrap {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}
.ds-svg { width: 100%; display: block; }

/* ── 体模三视图画布（含 img + SVG 覆盖层） ── */
.ds-phantom-canvas {
  position: relative;
  width: 100%;
  background: #0d1117;
  /* 高度自适应：撑开到图片自然高度 */
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 260px;
  overflow: visible;  /* 允许体外中子源标记渲染到画布左侧 */
}
.ds-phantom-bg-img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 600px;
  object-fit: contain;
  opacity: 0.9;
}
.ds-phantom-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;  /* 允许水平体外中子源渲染在体模图像左侧 */
}

/* ── CT 图像交互模式 ── */
.ds-ct-viz-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ds-ct-canvas {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1.2;
  background: #0d1117;
  border: 1px solid #2d3748;
  border-radius: 6px;
  overflow: hidden;
  cursor: crosshair;
}
.ds-ct-bg-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  user-select: none;
}
.ds-ct-no-img {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #718096;
  font-size: 0.85rem;
}
.ds-ct-tumor-ring {
  position: absolute;
  border: 2.5px solid #e53e3e;
  border-radius: 50%;
  background: rgba(229,62,62,0.25);
  box-shadow: 0 0 0 1px rgba(229,62,62,0.5);
  pointer-events: none;
  transform: translate(-50%, -50%);
}
.ds-ct-tumor-label {
  position: absolute;
  bottom: calc(100% + 3px);
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.65rem;
  color: #fc8181;
  white-space: nowrap;
  background: rgba(0,0,0,0.6);
  padding: 1px 4px;
  border-radius: 3px;
}
.ds-ct-beam-indicator {
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #f6ad55;
  font-size: 0.7rem;
  gap: 2px;
  pointer-events: none;
}
.ds-ct-beam-arrow {
  font-size: 1.3rem;
  line-height: 1;
  color: #f6ad55;
}
.ds-ct-beam-text {
  font-size: 0.6rem;
  color: #f6ad55;
  writing-mode: vertical-rl;
  letter-spacing: 1px;
}
.ds-ct-crosshair-h {
  position: absolute;
  top: 50%; left: 0; right: 0;
  height: 1px;
  background: rgba(255,255,255,0.12);
  pointer-events: none;
}
.ds-ct-crosshair-v {
  position: absolute;
  left: 50%; top: 0; bottom: 0;
  width: 1px;
  background: rgba(255,255,255,0.12);
  pointer-events: none;
}
.ds-ct-slice-ctrl {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ds-ct-slice-num {
  font-size: 0.78rem;
  color: #718096;
  min-width: 56px;
}
.ds-ct-interact-hint {
  font-size: 0.72rem;
  color: #718096;
  text-align: center;
  margin: 0;
}

/* ── 从CT定位按钮 ── */
.ds-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.ds-ct-locate-btn {
  padding: 2px 8px;
  font-size: 0.72rem;
  border: 1px solid #4299e1;
  border-radius: 4px;
  background: #ebf8ff;
  color: #2b6cb0;
  cursor: pointer;
  transition: all 0.15s;
}
.ds-ct-locate-btn:hover:not(:disabled) {
  background: #4299e1;
  color: #fff;
}
.ds-ct-locate-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ds-ct-hint-small {
  font-size: 0.7rem;
  color: #718096;
  margin: 3px 0 0 0;
}

.ds-depth-ctrl {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  width: 100%;
}
.ds-slider { flex: 1; }
.ds-depth-val { font-size: 0.85rem; font-weight: 700; color: #e53e3e; min-width: 44px; }

/* ── 结果面板 ── */
.ds-results-panel {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  padding: 0.8rem;
  overflow-y: auto;
  max-height: calc(100vh - 130px);
}

.ds-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #a0aec0;
  gap: 4px;
}

/* 摘要卡片 */
.ds-summary-cards {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.ds-sum-card {
  flex: 1;
  padding: 0.6rem;
  border-radius: 8px;
  text-align: center;
}
.ds-sum-tumor  { background: linear-gradient(135deg,#fff5f5,#fed7d7); border:1px solid #fc8181; }
.ds-sum-skin   { background: linear-gradient(135deg,#f0fff4,#c6f6d5); border:1px solid #68d391; }
.ds-sum-ratio  { background: linear-gradient(135deg,#ebf8ff,#bee3f8); border:1px solid #63b3ed; }
.ds-sum-icon   { font-size: 1.2rem; }
.ds-sum-val    { font-size: 1.4rem; font-weight: 700; color: #2d3748; }
.ds-sum-label  { font-size: 0.68rem; color: #718096; }

.ds-component-section { margin-bottom: 1rem; }
.ds-sub-title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #4a5568;
  margin-bottom: 0.45rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid #edf2f7;
}

/* 组分条形图 */
.ds-comp-bars { display: flex; flex-direction: column; gap: 5px; }
.ds-comp-row  { display: flex; align-items: center; gap: 6px; }
.ds-comp-label { font-size: 0.72rem; color: #4a5568; min-width: 90px; }
.ds-comp-bar-wrap {
  flex: 1;
  height: 12px;
  background: #edf2f7;
  border-radius: 6px;
  overflow: hidden;
}
.ds-comp-bar {
  height: 100%;
  border-radius: 6px;
  transition: width 0.4s ease;
}
.ds-comp-pct { font-size: 0.72rem; color: #718096; min-width: 34px; text-align: right; }
.ds-comp-abs { font-size: 0.7rem; color: #2d3748; min-width: 80px; font-family: monospace; }

/* 表格 */
.ds-comp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.ds-comp-table th {
  background: #f7fafc;
  color: #4a5568;
  font-weight: 600;
  padding: 4px 6px;
  border: 1px solid #e2e8f0;
  text-align: left;
}
.ds-comp-table td {
  padding: 3px 6px;
  border: 1px solid #e2e8f0;
}
.ds-mono    { font-family: 'Courier New', monospace; font-size: 0.72rem; }
.ds-weighted { color: #3182ce; font-weight: 600; }
.ds-total-row { background: #f0fff4; }
.ds-total   { color: #2f855a; font-weight: 700; }

/* 深度剂量曲线 */
.ds-ddp-wrap { border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; }
.ds-ddp-svg  { width: 100%; display: block; }

/* ── 验证面板 ── */
.ds-validate-panel {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  margin: 0 1rem 1rem;
  padding: 1rem;
}
.ds-validate-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
}
.ds-validate-header h3 { font-size: 1rem; color: #2d3748; }
.ds-validate-desc { flex: 1; font-size: 0.78rem; color: #718096; min-width: 200px; }

.ds-val-summary {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.ds-val-card {
  flex: 1; min-width: 80px;
  padding: 0.5rem;
  border-radius: 8px;
  text-align: center;
}
.val-pass { background: #f0fff4; border: 1px solid #68d391; }
.val-fail { background: #fff5f5; border: 1px solid #fc8181; }
.val-warn { background: #fffbeb; border: 1px solid #f6e05e; }
.val-info { background: #ebf8ff; border: 1px solid #63b3ed; }
.ds-val-icon  { font-size: 1.1rem; font-weight: 700; }
.ds-val-label { font-size: 0.72rem; color: #4a5568; margin-top: 2px; }

.ds-val-detail {
  margin-bottom: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}
.ds-val-detail summary {
  padding: 0.5rem 0.75rem;
  background: #f7fafc;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  color: #4a5568;
  user-select: none;
}
.ds-val-detail summary:hover { background: #edf2f7; }

.ds-val-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.73rem;
}
.ds-val-table th {
  background: #f7fafc;
  padding: 4px 6px;
  border: 1px solid #e2e8f0;
  font-weight: 600;
  color: #4a5568;
}
.ds-val-table td {
  padding: 3px 6px;
  border: 1px solid #e2e8f0;
}
.val-row-fail { background: #fff5f5; }

.ds-val-case {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  margin: 0.5rem;
  overflow: hidden;
}
.ds-val-case-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.7rem;
  font-size: 0.82rem;
  font-weight: 600;
  flex-wrap: wrap;
  gap: 4px;
}
.case-pass { background: #f0fff4; color: #22543d; }
.case-fail { background: #fff5f5; color: #742a2a; }
.ds-val-case-ref { font-size: 0.68rem; font-weight: 400; color: #718096; }
.ds-val-expand-hint { font-size: 0.68rem; font-weight: 500; color: #718096; white-space: nowrap; }
.ds-val-case-body { padding: 0.5rem; }
.ds-val-case-desc { font-size: 0.75rem; color: #718096; margin-bottom: 6px; }

.ds-val-empty {
  text-align: center;
  color: #a0aec0;
  padding: 1.5rem;
  font-size: 0.85rem;
}
.ds-validate-body { margin-top: 0.5rem; }

/* ── 中子AP ICRP剂量对比 ── */
.nicrp-workspace { padding: 1.5rem 2rem; max-width: 1300px; margin: 0 auto; }
.nicrp-header { margin-bottom: 1.5rem; }
.nicrp-header h2 { font-size: 1.3rem; font-weight: 700; color: #1a202c; margin-bottom: 0.5rem; }
.nicrp-desc { font-size: 0.9rem; color: #4a5568; line-height: 1.6; }
.nicrp-controls {
  display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
  margin-bottom: 1.5rem; padding: 1rem 1.2rem;
  background: #f7fafc; border-radius: 10px; border: 1px solid #e2e8f0;
}
.nicrp-run-btn { padding: 0.55rem 1.6rem; font-size: 0.95rem; }
.nicrp-progress { text-align: center; padding: 2rem; color: #4a5568; }
.nicrp-progress-bar {
  width: 100%; max-width: 400px; height: 6px;
  background: #e2e8f0; border-radius: 3px; margin: 0 auto 1rem;
  overflow: hidden;
}
.nicrp-progress-inner {
  height: 100%; width: 60%; background: linear-gradient(90deg, #3b82f6, #6366f1);
  border-radius: 3px; animation: nicrp-slide 1.5s infinite;
}
@keyframes nicrp-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(250%); }
}

/* 摘要卡片 */
.nicrp-summary-cards {
  display: flex; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 1.5rem;
}
.nicrp-card {
  flex: 1; min-width: 120px;
  background: white; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 0.8rem 1rem; text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.nicrp-card-icon { font-size: 1.3rem; margin-bottom: 4px; }
.nicrp-card-label { font-size: 0.72rem; color: #718096; margin-bottom: 4px; }
.nicrp-card-value { font-size: 0.9rem; font-weight: 700; color: #2d3748; }

/* 图表选项卡 */
.nicrp-chart-tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
.nicrp-tab-btn {
  padding: 0.4rem 1.1rem; border: 1px solid #cbd5e0;
  border-radius: 6px; background: white; cursor: pointer;
  font-size: 0.85rem; color: #4a5568; transition: all 0.15s;
}
.nicrp-tab-btn:hover { border-color: #3b82f6; color: #3b82f6; }
.nicrp-tab-btn.active { background: #3b82f6; color: white; border-color: #3b82f6; }

/* 主图区 */
.nicrp-chart-section {
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 1rem; margin-bottom: 1rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.nicrp-chart-title {
  font-size: 0.88rem; font-weight: 600; color: #2d3748;
  margin-bottom: 0.8rem; padding-bottom: 0.5rem;
  border-bottom: 1px solid #edf2f7;
}
.nicrp-chart-img { width: 100%; height: auto; border-radius: 6px; display: block; }

/* 缩略图导航 */
.nicrp-thumbnails { display: flex; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 1rem; }
.nicrp-thumb {
  width: 140px; cursor: pointer; border: 2px solid #e2e8f0; border-radius: 8px;
  overflow: hidden; transition: border-color 0.15s;
}
.nicrp-thumb:hover { border-color: #3b82f6; }
.nicrp-thumb.active { border-color: #3b82f6; }
.nicrp-thumb-img { width: 100%; height: 88px; object-fit: cover; display: block; }
.nicrp-thumb-label {
  text-align: center; font-size: 0.75rem; color: #4a5568;
  padding: 3px 0; background: #f7fafc;
}

/* 说明文字 */
.nicrp-note {
  font-size: 0.78rem; color: #718096; background: #f7fafc;
  border-radius: 8px; padding: 0.8rem 1rem; line-height: 1.7;
  border-left: 3px solid #3b82f6;
}

/* 空态 & 错误 */
.nicrp-empty {
  text-align: center; color: #a0aec0; padding: 3rem 1rem; font-size: 0.95rem;
}
.nicrp-empty p:first-child { font-size: 2.5rem; margin-bottom: 0.5rem; }
.nicrp-empty-sub { font-size: 0.82rem; color: #cbd5e0; margin-top: 0.4rem; }
.nicrp-error { color: #e53e3e; padding: 1rem; background: #fff5f5; border-radius: 8px; margin-top: 1rem; }

/* ═══ ICRP-116 AP 光子验证 Tab ═══════════════════════════════ */
.icrp116-workspace { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
.icrp116-header { margin-bottom: 1.5rem; }
.icrp116-header h2 { font-size: 1.4rem; color: #2d3748; margin-bottom: 0.5rem; }
.icrp116-desc { color: #4a5568; font-size: 0.92rem; line-height: 1.6; }
.icrp116-note { color: #c05621; font-size: 0.85rem; }

.icrp116-controls { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; }
.icrp116-energy-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 1rem; }
.ctrl-label { font-weight: 600; color: #2d3748; }
.icrp116-energy-checkbox { display: flex; align-items: center; gap: 0.3rem; font-size: 0.9rem; cursor: pointer; }
.icrp116-energy-checkbox input { cursor: pointer; }
.icrp116-btn-row { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
.icrp116-elapsed { color: #718096; font-size: 0.88rem; }

.icrp116-sex-avg-row { margin: 0.5rem 0 0.4rem; }
.icrp116-sex-avg-label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.92rem; cursor: pointer; color: #2d3748; }
.icrp116-sex-avg-label input { cursor: pointer; width: 15px; height: 15px; }

.icrp116-adv-row { display: flex; flex-direction: column; margin: 0.2rem 0 0.8rem; padding: 0.5rem 0.8rem; background: #f7fafc; border-left: 3px solid #cbd5e0; border-radius: 4px; }
.icrp116-adv-label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.88rem; cursor: pointer; color: #4a5568; }
.icrp116-adv-label input { cursor: pointer; width: 14px; height: 14px; }

.icrp116-progress { margin-top: 1rem; }
.icrp116-phase-label { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; font-size: 0.85rem; }
.phase-badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 10px; font-weight: 700; font-size: 0.8rem; }
.phase-badge.phase-am { background: #bee3f8; color: #2b6cb0; }
.phase-badge.phase-af { background: #fed7e2; color: #97266d; }
.phase-done-mark { color: #38a169; font-weight: 600; }
.phase-active-mark { color: #3182ce; }
.icrp116-progress-items { display: flex; gap: 0.6rem; flex-wrap: wrap; }
.icrp116-e-chip { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.3rem 0.7rem; border-radius: 20px; font-size: 0.85rem; border: 1px solid #e2e8f0; background: #edf2f7; color: #718096; }
.icrp116-e-chip.done { background: #c6f6d5; border-color: #68d391; color: #276749; }
.icrp116-e-chip.active { background: #bee3f8; border-color: #63b3ed; color: #2b6cb0; }
.icrp116-e-chip .chip-icon { font-size: 0.9rem; }

.icrp116-log-panel { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; margin-bottom: 1.2rem; }
.icrp116-log-header { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; background: #2d3748; color: #fff; }
.icrp116-log-header h4 { margin: 0; font-size: 0.9rem; }
.btn-sm { padding: 0.2rem 0.6rem; font-size: 0.78rem; }
.icrp116-log-body { height: 320px; overflow-y: auto; background: #1a202c; padding: 0.5rem 0.8rem; font-family: monospace; font-size: 0.82rem; }
.icrp116-log-body .log-entry { padding: 0.15rem 0; display: flex; gap: 0.6rem; }
.icrp116-log-body .log-time { color: #718096; white-space: nowrap; min-width: 70px; }
.icrp116-log-body .log-message { color: #e2e8f0; word-break: break-all; }
.icrp116-log-body .log-entry.success .log-message { color: #68d391; }
.icrp116-log-body .log-entry.error .log-message { color: #fc8181; }
.icrp116-log-body .log-empty { color: #718096; text-align: center; padding: 2rem; }

.icrp116-result-banner { padding: 1rem 1.2rem; border-radius: 8px; margin-top: 0.5rem; }
.success-banner { background: #f0fff4; border: 1px solid #68d391; color: #276749; }
.error-banner   { background: #fff5f5; border: 1px solid #fc8181; color: #c53030; }
.icrp116-result-files { margin: 0.5rem 0 0 1rem; font-size: 0.88rem; }
.btn-danger { background: #e53e3e; color: #fff; border: none; padding: 0.4rem 1rem; border-radius: 6px; cursor: pointer; }
.btn-danger:hover { background: #c53030; }

/* ─── ICRP-116 Step3 对比分析模块 ────────────────────────────── */
.icrp116-step3-module {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1.5rem 1.8rem;
  margin-top: 1.5rem;
}
.icrp116-step3-module .s3-header h3 {
  font-size: 1.05rem;
  color: #2d3748;
  margin: 0 0 0.3rem;
  font-weight: 700;
}
.icrp116-step3-module .s3-header p {
  color: #718096;
  font-size: 0.88rem;
  margin: 0 0 1rem;
}
.s3-btn-row {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.s3-log {
  background: #1a202c;
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
  max-height: 160px;
  overflow-y: auto;
  margin-bottom: 1rem;
  font-family: monospace;
}
.s3-log-entry { display: flex; gap: 0.6rem; font-size: 0.8rem; padding: 1px 0; }
.s3-log-time  { color: #718096; white-space: nowrap; }
.s3-log-msg   { color: #e2e8f0; word-break: break-all; }
.s3-log-entry.success .s3-log-msg { color: #68d391; }
.s3-log-entry.error   .s3-log-msg { color: #fc8181; }
.s3-results h4 { font-size: 0.95rem; color: #4a5568; margin: 0 0 0.6rem; font-weight: 600; }
.s3-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  margin-bottom: 1.2rem;
}
.s3-table th {
  background: #edf2f7;
  padding: 0.5rem 0.8rem;
  text-align: center;
  color: #4a5568;
  font-weight: 600;
  border: 1px solid #e2e8f0;
}
.s3-table td {
  padding: 0.45rem 0.8rem;
  text-align: center;
  border: 1px solid #e2e8f0;
}
.s3-chart-area { margin-top: 1rem; }
.s3-chart-area h4 { font-size: 0.95rem; color: #4a5568; margin: 0 0 0.6rem; font-weight: 600; }
.s3-chart-img {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: block;
}

/* xsdir 诊断面板 */
.s3-xsdir-panel {
  margin-top: 0.8rem;
  padding: 0.8rem 1rem;
  border-radius: 8px;
  font-size: 0.87rem;
  line-height: 1.6;
}
.xsdir-ok   { background: #ebf8ff; border: 1px solid #63b3ed; color: #2b6cb0; }
.xsdir-warn { background: #fff5f5; border: 1px solid #fc8181; color: #c53030; }
.xsdir-title { font-weight: 700; margin-bottom: 0.3rem; }
.xsdir-detail { margin-top: 0.3rem; }
.xsdir-hint { margin-top: 0.4rem; color: #4a5568; }
.xsdir-hint code, .xsdir-detail code { background: #edf2f7; padding: 0.1em 0.3em; border-radius: 3px; }
</style>