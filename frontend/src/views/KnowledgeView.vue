<template>
  <div class="knowledge-view">
    <div class="kb-container">
      <h3>📚 知识库管理</h3>
      <p class="desc">上传 <strong>.docx</strong> 格式的 Word 文档，文档内容将被自动分块并向量化，供 Agent 检索问答。</p>

      <!-- 文件上传区域 -->
      <div
        class="upload-area"
        :class="{ dragging: isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
        @click="triggerFileInput"
      >
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".docx"
          @change="handleFileSelect"
          style="display: none"
        />
        <div class="upload-icon">📄</div>
        <p>点击或拖拽 .docx 文件到此处</p>
      </div>

      <!-- 已选文件列表 -->
      <div v-if="selectedFiles.length > 0" class="selected-files">
        <div class="file-item" v-for="(file, idx) in selectedFiles" :key="idx">
          <span>📎 {{ file.name }}</span>
          <button @click="removeFile(idx)" class="remove-btn">×</button>
        </div>
        <button @click="uploadFiles" :disabled="uploading" class="upload-btn">
          <span v-if="uploading" class="spinner-small"></span>
          <span v-else>📤 导入到知识库</span>
        </button>
      </div>

      <!-- 上传结果 -->
      <div v-if="uploadResults.length > 0" class="results">
        <h4>导入结果</h4>
        <div v-for="(result, idx) in uploadResults" :key="idx" class="result-item">
          {{ result }}
        </div>
      </div>

      <!-- 知识库状态 -->
      <div class="status-box">
        <h4>📊 当前状态</h4>
        <p class="status-msg">{{ statusMessage || '加载中...' }}</p>
        <div v-if="statusFiles.length > 0" class="file-list">
          <div class="file-tag" v-for="(file, idx) in statusFiles" :key="idx">📄 {{ file }}</div>
        </div>
        <button @click="fetchStatus" class="refresh-btn">🔄 刷新</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const fileInput = ref(null)
const selectedFiles = ref([])
const uploading = ref(false)
const uploadResults = ref([])
const kbStatus = ref('')
const statusMessage = ref('')
const statusFiles = ref([])
const isDragging = ref(false)

// 触发文件选择
function triggerFileInput() {
  fileInput.value?.click()
}

// 文件选择处理
function handleFileSelect(e) {
  const files = Array.from(e.target.files || [])
  addFiles(files)
}

// 拖拽放置处理
function handleDrop(e) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  addFiles(files)
}

// 添加文件到列表
function addFiles(files) {
  const docxFiles = files.filter(f => f.name.toLowerCase().endsWith('.docx'))
  if (docxFiles.length < files.length) {
    alert('仅支持 .docx 格式文件，非 Word 文件已跳过')
  }
  selectedFiles.value.push(...docxFiles)
}

// 移除已选文件
function removeFile(idx) {
  selectedFiles.value.splice(idx, 1)
}

// 上传文件到知识库
async function uploadFiles() {
  if (selectedFiles.value.length === 0) return

  uploading.value = true
  uploadResults.value = []

  try {
    const formData = new FormData()
    for (const file of selectedFiles.value) {
      formData.append('files', file)
    }

    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`上传失败: HTTP ${response.status}`)
    }

    const data = await response.json()
    uploadResults.value = data.results || []
    applyStatus(data.status)
    selectedFiles.value = []  // 清空已选
  } catch (e) {
    uploadResults.value = [`❌ 上传出错：${e.message}`]
  } finally {
    uploading.value = false
  }
}

// 解析状态数据
function applyStatus(status) {
  if (typeof status === 'string') {
    statusMessage.value = status
    statusFiles.value = []
  } else if (status && typeof status === 'object') {
    statusMessage.value = status.message || ''
    statusFiles.value = status.files || []
  }
}

// 获取知识库状态
async function fetchStatus() {
  try {
    const response = await fetch('/api/kb/status')
    const data = await response.json()
    applyStatus(data.status)
  } catch (e) {
    statusMessage.value = `获取状态失败：${e.message}`
    statusFiles.value = []
  }
}

// 组件挂载时获取状态
onMounted(fetchStatus)
</script>

<style scoped>
.knowledge-view {
  height: 100%;
  overflow-y: auto;
  padding: 20px;
}

.kb-container {
  max-width: 700px;
  margin: 0 auto;
}

.kb-container h3 {
  margin: 0 0 8px;
  color: #333;
}

.desc {
  color: #666;
  font-size: 0.9rem;
  margin: 0 0 24px;
}

.upload-area {
  border: 2px dashed #d0d5e0;
  border-radius: 16px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafbfd;
}

.upload-area:hover,
.upload-area.dragging {
  border-color: #667eea;
  background: #f0f2ff;
}

.upload-icon {
  font-size: 36px;
  margin-bottom: 12px;
}

.upload-area p {
  margin: 0;
  color: #666;
}

.selected-files {
  margin-top: 16px;
  padding: 16px;
  background: #f8f9fc;
  border-radius: 12px;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: white;
  border-radius: 8px;
  margin-bottom: 8px;
}

.remove-btn {
  background: none;
  border: none;
  color: #999;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 4px;
}

.remove-btn:hover {
  color: #ff6b6b;
}

.upload-btn {
  width: 100%;
  padding: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 1rem;
  cursor: pointer;
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.upload-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinner-small {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.results {
  margin-top: 20px;
  padding: 16px;
  background: #f8f9fc;
  border-radius: 12px;
}

.results h4 {
  margin: 0 0 12px;
  color: #333;
}

.result-item {
  padding: 6px 0;
  font-size: 0.9rem;
  border-bottom: 1px solid #e8ecf4;
}

.result-item:last-child {
  border-bottom: none;
}

.status-box {
  margin-top: 24px;
  padding: 16px;
  background: #f8f9fc;
  border-radius: 12px;
}

.status-box h4 {
  margin: 0 0 8px;
  color: #333;
}

.status-box p {
  margin: 0;
  color: #555;
  font-family: monospace;
  font-size: 0.9rem;
}

.status-msg {
  margin-bottom: 12px !important;
}

.file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.file-tag {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  background: white;
  border: 1px solid #e0e4ed;
  border-radius: 8px;
  font-size: 0.85rem;
  color: #444;
}

.refresh-btn {
  margin-top: 12px;
  padding: 6px 14px;
  background: white;
  border: 1px solid #d0d5e0;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover {
  border-color: #667eea;
  color: #667eea;
}
</style>
