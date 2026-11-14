<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NConfigProvider } from 'naive-ui'
import ExpiryFields from './ExpiryFields.vue'

const theme = { common: { primaryColor: '#08745a', primaryColorHover: '#09654f', primaryColorPressed: '#064d3d', borderRadius: '8px', fontFamily: 'Geist, system-ui, sans-serif' } }
const user = ref(null)
const ready = ref(false)
const page = ref('overview')
const overview = ref({ total: 0, active: 0, paused: 0, pv: 0, recent: [] })
const statusFilter = ref('')
const clock = ref(Date.now())
const changedPassword = ref({ current: '', replacement: '' })
const policyFields = [
  ['default_ips', '默认 IP 名额', 10000], ['max_upload_mb', '单文件上限（MB）', 50],
  ['active_limit', '账号有效发布上限', 10000], ['storage_limit_mb', '账号存储上限（MB）', 100000],
  ['hourly_limit', '账号每小时可发布数', 1000],
]
const records = ref([])
const accounts = ref([])
const devices = ref([])
const settings = ref({ max_days: null })
const offset = ref(0)
const pageSize = ref(20)
const total = ref(0)
const selected = ref([])
const filters = ref({ agent_name: '', device_name: '', owner: '', source: '', sort: 'newest' })
const resumeIps = ref(null)
const displayedPage = computed(() => Math.floor(offset.value / pageSize.value) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const allSelected = computed(() => records.value.length > 0 && selected.value.length === records.value.length)
const selectedRows = computed(() => records.value.filter(row => selected.value.includes(row.id)))
const canBatchPause = computed(() => selectedRows.value.every(row => row.status === 'active'))
const canBatchResume = computed(() => selectedRows.value.every(row => row.status === 'paused'))
const canBatchClose = computed(() => selectedRows.value.every(row => ['active', 'paused'].includes(row.status)))
const canBatchDelete = computed(() => selectedRows.value.every(row => !['active', 'paused'].includes(row.status)))
const operationLabels = { pause: '暂停发布', resume: '恢复发布', close: '永久关闭', delete: '删除记录' }
const search = ref('')
const error = ref('')
const busy = ref(false)
const notice = ref('')
const username = ref('')
const password = ref('')
const file = ref(null)
const compatibility = ref([])
const maxIps = ref(10)
const pathNote = ref('')
const result = ref(null)
const modal = ref(null)
const maxDays = ref('')
const defaultExpiry = ref({ mode: 'preset', preset: '24h', date: '' })
const editor = ref({ mode: 'preset', preset: '24h', date: '' })
const expiry = ref({ mode: 'preset', preset: '24h', date: '' })
const account = ref({ username: '', password: '', admin: false, disabled: false })
const admin = computed(() => user.value?.role === 'admin')
const statusLabels = { active: '有效', paused: '已暂停', expired: '已过期', closed: '已关闭', missing: '内容不可用' }

async function api(path, options = {}) {
  const request = { ...options }
  if (request.body && !(request.body instanceof FormData)) {
    request.body = JSON.stringify(request.body)
    request.headers = { 'Content-Type': 'application/json' }
  }
  const response = await fetch('/api/v1' + path, request)
  if (response.status === 204) return null
  const data = await response.json()
  if (!response.ok) {
    if (response.status === 401 && path !== '/session') user.value = null
    throw new Error(typeof data.detail === 'string' ? data.detail : '请检查填写内容后重试。')
  }
  return data
}

async function perform(action) {
  if (busy.value) return
  error.value = ''
  notice.value = ''
  busy.value = true
  try { await action() }
  catch (reason) { error.value = reason.message }
  finally { busy.value = false }
}

async function refresh() {
  const parameters = new URLSearchParams({ limit: String(pageSize.value), offset: String(offset.value), search: search.value })
  if (statusFilter.value) parameters.set('status', statusFilter.value)
  for (const [key, value] of Object.entries(filters.value)) if (value && (key !== 'owner' || admin.value)) parameters.set(key, value)
  const data = await api('/publishes?' + parameters)
  total.value = data.total
  if (offset.value && offset.value >= data.total) {
    offset.value = Math.max(0, Math.ceil(data.total / pageSize.value) - 1) * pageSize.value
    return refresh()
  }
  records.value = data.items
  selected.value = []
}

function openRecords(status = '') {
  search.value = ''
  statusFilter.value = status
  filters.value = { agent_name: '', device_name: '', owner: '', source: '', sort: 'newest' }
  offset.value = 0
  return navigate('records')
}

async function loadPage(name) {
  page.value = name
  if (name === 'records') await refresh()
  if (name === 'overview') overview.value = await api('/overview')
  if (name === 'accounts') accounts.value = await api('/admin/users')
  if (name === 'devices') devices.value = await api('/authorizations')
  if (name === 'settings' || name === 'new') {
    settings.value = await api('/settings')
    maxDays.value = settings.value.max_days ?? ''
    defaultExpiry.value.preset = settings.value.default_preset
    if (name === 'new') {
      pathNote.value = ''
      result.value = null
      file.value = null
      compatibility.value = []
      maxIps.value = settings.value.default_ips
      expiry.value = { mode: 'preset', preset: settings.value.default_preset, date: '' }
    }
  }
}

function navigate(name) {
  return perform(() => loadPage(name))
}

function returnToConsent() {
  const destination = new URLSearchParams(location.search).get('authorize')
  if (destination?.startsWith('/oauth/authorize?')) {
    location.assign(destination)
    return true
  }
  return false
}

async function login() {
  await perform(async () => {
    user.value = await api('/session', { method: 'POST', body: { username: username.value, password: password.value } })
    password.value = ''
    if (!returnToConsent()) await loadPage('overview')
  })
}

async function logout() {
  await perform(async () => {
    await api('/session', { method: 'DELETE' })
    user.value = null
    records.value = []
    accounts.value = []
    devices.value = []
    result.value = null
  })
}

onMounted(async () => {
  try {
    user.value = await api('/session')
    if (!returnToConsent()) await loadPage('overview')
  } catch {
    user.value = null
  } finally {
    ready.value = true
  }
})

const timer = setInterval(() => { clock.value = Date.now() }, 1000)
onUnmounted(() => clearInterval(timer))

function remaining(row) {
  if (!row.expires_at || row.status !== 'active') return ''
  const seconds = Math.max(0, Math.floor((Date.parse(row.expires_at) - clock.value) / 1000))
  if (seconds >= 86400) return '剩余 ' + Math.ceil(seconds / 86400) + ' 天'
  if (seconds >= 3600) return '剩余 ' + Math.ceil(seconds / 3600) + ' 小时'
  if (seconds >= 60) return '剩余 ' + Math.ceil(seconds / 60) + ' 分钟'
  return seconds ? '剩余 ' + seconds + ' 秒' : '已到期'
}

function expiryBody(choice) {
  return choice.mode === 'date' ? { at: new Date(choice.date).toISOString() } : { preset: choice.preset }
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '永久'
}

function changePage(delta) {
  return perform(async () => {
    offset.value = Math.max(0, offset.value + delta * pageSize.value)
    await refresh()
  })
}

function findRecords() {
  return perform(async () => {
    offset.value = 0
    await refresh()
  })
}

function createPublish(event) {
  const form = event.target
  return perform(async () => {
    const selectedFile = form.querySelector('input[type=file]').files[0]
    if (!selectedFile) throw new Error('请选择 HTML 文件。')
    const body = new FormData()
    body.set('file', selectedFile)
    body.set('expiry', JSON.stringify(expiryBody(expiry.value)))
    body.set('max_ips', String(maxIps.value))
    if (pathNote.value) body.set('path_note', pathNote.value)
    result.value = await api('/publishes', { method: 'POST', body })
    form.querySelector('input[type="file"]').value = ''
    file.value = null
    compatibility.value = []
    pathNote.value = ''
  })
}

async function chooseFile(event) {
  const selected = event.target.files[0]
  file.value = selected
  compatibility.value = []
  if (!selected || selected.size > settings.value.max_upload_mb * 1048576) return
  const source = await selected.text()
  if (file.value !== selected) return
  if (/<(?:iframe|frame)\b/i.test(source)) compatibility.value.push('嵌套 iframe 将被阻止。')
  if (/<form\b/i.test(source)) compatibility.value.push('表单提交将被阻止，页内计算仍可运行。')
  if (/(?:\b(?:src|href|poster)\s*=\s*["']?(?:https?:)?\/\/|\b(?:fetch|WebSocket|XMLHttpRequest)\s*\()/i.test(source)) {
    compatibility.value.push('检测到可能的外部依赖。预览将限制外部资源和联网请求。')
  }
}

async function copy(url) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(url)
      notice.value = '链接已复制。'
      return
    } catch {
      // The selectable URL remains available when clipboard access is denied.
    }
  }
  modal.value = { kind: 'link', url }
}

function copyRecord(row) {
  return perform(async () => copy((await api('/publishes/' + row.id + '/link')).url))
}

function showExpiry(row) {
  const current = row.expires_at ? new Date(row.expires_at) : null
  if (current) current.setMinutes(current.getMinutes() - current.getTimezoneOffset())
  editor.value = current
    ? { mode: 'date', preset: '24h', date: current.toISOString().slice(0, 16) }
    : { mode: 'preset', preset: settings.value.max_days ? '24h' : 'forever', date: '' }
  modal.value = { kind: 'expiry', row }
  return perform(async () => { settings.value = await api('/settings') })
}

function showOperation(kind, row = null) {
  error.value = ''
  if (kind === 'resume') {
    editor.value = { mode: 'preset', preset: '', date: '' }
    resumeIps.value = null
    return perform(async () => {
      settings.value = await api('/settings')
      modal.value = { kind, row }
    })
  }
  modal.value = { kind, row }
}

function updateRecord() {
  return perform(async () => {
    const { row, kind } = modal.value
    const endpoint = row ? '/publishes/' + row.id : null
    if (kind === 'expiry') {
      await api(endpoint + '/expiry', { method: 'PUT', body: expiryBody(editor.value) })
    } else {
      let options
      if (kind === 'resume') {
        if (editor.value.mode === 'preset' && !editor.value.preset) throw new Error('请选择恢复后的有效期。')
        options = { expiry: expiryBody(editor.value), max_ips: resumeIps.value }
      }
      if (!row) {
        await api('/publishes/batch', { method: 'POST', body: { ids: selected.value, action: kind, resume: options } })
      } else if (kind === 'delete') {
        await api(endpoint, { method: 'DELETE' })
      } else {
        await api(endpoint + '/' + kind, { method: 'POST', body: options })
      }
    }
    const count = row ? 1 : selected.value.length
    modal.value = null
    await refresh()
    notice.value = kind === 'expiry' ? '到期时间已更新。' : '已处理 ' + count + ' 条记录：' + operationLabels[kind] + '。'
  })
}

function openAccount(row = null) {
  account.value = {
    username: row?.username ?? '', password: '', admin: row?.role === 'admin', disabled: row?.disabled ?? false,
  }
  modal.value = { kind: 'account', row }
}

function saveAccount() {
  return perform(async () => {
    const row = modal.value.row
    const body = { username: account.value.username, admin: account.value.admin }
    if (account.value.password) body.password = account.value.password
    if (row && row.disabled !== account.value.disabled) body.disabled = account.value.disabled
    if (row && (row.role === 'admin') === body.admin) delete body.admin
    await api('/admin/users' + (row ? '/' + row.id : ''), { method: row ? 'PATCH' : 'POST', body })
    modal.value = null
    accounts.value = await api('/admin/users')
    notice.value = '账号已保存。'
  })
}

function revokeDevice() {
  return perform(async () => {
    await api('/authorizations/' + modal.value.row.id, { method: 'DELETE' })
    modal.value = null
    devices.value = await api('/authorizations')
    notice.value = '设备授权已撤销。'
  })
}

function deleteAccount() {
  return perform(async () => {
    await api('/admin/users/' + modal.value.row.id, { method: 'DELETE' })
    modal.value = null
    accounts.value = await api('/admin/users')
    notice.value = '账号已删除。'
  })
}

function changePassword() {
  return perform(async () => {
    await api('/account/password', { method: 'PUT', body: changedPassword.value })
    changedPassword.value = { current: '', replacement: '' }
    modal.value = null
    user.value = null
  })
}

function saveSettings() {
  return perform(async () => {
    const body = { max_days: maxDays.value === '' ? null : Number(maxDays.value), default_preset: defaultExpiry.value.preset }
    for (const [key] of policyFields) body[key] = Number(settings.value[key])
    settings.value = await api('/settings', { method: 'PUT', body })
    notice.value = '系统设置已保存。'
  })
}

const dialog = ref(null)
watch(modal, async (value) => {
  if (value && dialog.value && !dialog.value.open) dialog.value.showModal()
  if (!value && dialog.value?.open) dialog.value.close()
}, { flush: 'post' })
</script>

<template>
  <NConfigProvider :theme-overrides="theme">
    <div v-if="!ready" class="loading">正在加载…</div>
    <main v-else-if="!user" class="login">
      <form class="login-panel" @submit.prevent="login">
        <div class="brand"><img class="mark" src="/wisplink-icon-64x64.png" width="34" height="34" alt=""> WispLink</div>
        <h1>登录控制台</h1>
        <label>用户名<input v-model="username" name="username" autocomplete="username" required></label>
        <label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" required></label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <NButton type="primary" attr-type="submit" :loading="busy" block>登录</NButton>
      </form>
    </main>
    <div v-else class="layout">
      <aside class="sidebar">
        <div class="brand"><img class="mark" src="/wisplink-icon-64x64.png" width="34" height="34" alt=""> WispLink</div>
        <nav aria-label="控制台">
          <button :aria-current="page === 'overview' ? 'page' : undefined" @click="navigate('overview')">首页概览</button>
          <button :aria-current="page === 'new' ? 'page' : undefined" @click="navigate('new')">新建发布</button>
          <button :aria-current="page === 'records' ? 'page' : undefined" @click="navigate('records')">发布记录</button>
          <button v-if="admin" :aria-current="page === 'accounts' ? 'page' : undefined" @click="navigate('accounts')">账号管理</button>
          <button :aria-current="page === 'devices' ? 'page' : undefined" @click="navigate('devices')">授权设备</button>
          <button v-if="admin" :aria-current="page === 'settings' ? 'page' : undefined" @click="navigate('settings')">系统设置</button>
        </nav>
        <div class="sidebar-footer">
          <strong>{{ user.username }}</strong>
          <button @click="modal = { kind: 'password' }">改密码</button>
          <button @click="logout">退出</button>
        </div>
      </aside>

      <main class="workspace">
        <header v-if="page === 'overview'" class="page-heading">
          <div><h1>发布工作台</h1><p>查看链接状态，继续管理最近的发布。</p></div>
          <NButton type="primary" @click="navigate('new')">＋ 新建发布</NButton>
        </header>
        <header v-else-if="page === 'records'" class="page-heading">
          <div><h1>发布记录</h1><p>查看链接状态、到期时间和访问数据。</p></div>
        </header>
        <header v-else-if="page === 'new'" class="page-heading">
          <div><h1>新建发布</h1><p>上传单文件 HTML，生成可分享的预览链接。</p></div>
        </header>
        <header v-else-if="page === 'accounts'" class="page-heading">
          <h1>账号管理</h1><NButton type="primary" @click="openAccount()">新建账号</NButton>
        </header>
        <header v-else-if="page === 'devices'" class="page-heading">
          <div><h1>授权设备</h1><p>查看通过 WispLink CLI 授权的设备。</p></div>
          <NButton v-if="admin" tag="a" href="/api/v1/admin/agent-bundle">下载 Agent 接入包</NButton>
        </header>
        <header v-else class="page-heading"><h1>系统设置</h1></header>

        <p v-if="error && !modal" class="error" role="alert">{{ error }}</p>
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>

        <section v-if="page === 'overview'" class="dashboard">
          <div class="dashboard-metrics">
            <button class="metric-primary" @click="openRecords('active')"><span>有效链接</span><strong>{{ overview.active }}</strong><small>查看有效发布 →</small></button>
            <button @click="openRecords('paused')"><span>暂停发布</span><strong>{{ overview.paused }}</strong><small>查看待恢复发布 →</small></button>
            <div><span>累计浏览</span><strong>{{ overview.pv }}</strong><small>{{ overview.total }} 条发布</small></div>
          </div>
          <section class="panel recent">
            <header class="section-heading"><h2>最近发布</h2><NButton text @click="openRecords()">全部记录 →</NButton></header>
            <div v-if="!overview.recent.length" class="empty"><strong>暂无发布</strong><p>上传一份 HTML 即可生成第一条预览链接。</p></div>
            <ul v-else class="activity">
              <li v-for="row in overview.recent" :key="row.id">
                <div><strong>{{ row.filename }}</strong><small>{{ formatDate(row.created_at) }}</small></div>
                <span class="status" :data-status="row.status">{{ statusLabels[row.status] }}</span>
                <NButton v-if="row.status === 'active'" text @click="copyRecord(row)">复制链接</NButton>
              </li>
            </ul>
          </section>
        </section>
        <section v-if="page === 'records'" class="panel records-panel">
          <form class="toolbar record-filters" @submit.prevent="findRecords">
            <label>文件名<input v-model="search" type="search" maxlength="255" placeholder="搜索文件名"></label>
            <label>状态<select v-model="statusFilter"><option value="">全部状态</option><option v-for="(label, key) in statusLabels" :key="key" :value="key">{{ label }}</option></select></label>
            <label>来源<select v-model="filters.source"><option value="">全部来源</option><option value="web">网页版</option><option value="cli">CLI / Agent</option><option value="unknown">历史记录</option></select></label>
            <label>Agent 客户端<input v-model="filters.agent_name" maxlength="120" placeholder="例如 Codex"></label>
            <label>设备名称<input v-model="filters.device_name" maxlength="120" placeholder="搜索设备名称"></label>
            <label v-if="admin">发布者<input v-model="filters.owner" maxlength="80" placeholder="搜索账号"></label>
            <label>排序<select v-model="filters.sort"><option value="newest">最新发布</option><option value="oldest">最早发布</option><option value="expires">最早到期</option><option value="views">浏览最多</option></select></label>
            <div class="filter-actions"><NButton type="primary" attr-type="submit" :loading="busy">筛选</NButton><NButton @click="openRecords()">重置</NButton></div>
          </form>
          <div v-if="selected.length" class="selection-bar" role="status">
            <strong>已选 {{ selected.length }} 条</strong>
            <NButton size="small" :disabled="!canBatchPause" @click="showOperation('pause')">批量暂停</NButton>
            <NButton size="small" :disabled="!canBatchResume" @click="showOperation('resume')">批量恢复</NButton>
            <NButton size="small" :disabled="!canBatchClose" @click="showOperation('close')">批量关闭</NButton>
            <NButton size="small" :disabled="!canBatchDelete" @click="showOperation('delete')">批量删除</NButton>
            <NButton text @click="selected = []">取消选择</NButton>
          </div>
          <div v-if="records.length" class="table-scroll">
            <table>
              <thead><tr><th><input type="checkbox" :disabled="busy" aria-label="选择本页全部记录" :checked="allSelected" :indeterminate.prop="!!selected.length && !allSelected" @change="selected = $event.target.checked ? records.map(row => row.id) : []"></th><th>文件</th><th v-if="admin">发布者</th><th>Agent 客户端</th><th>设备名称</th><th>状态</th><th>到期时间</th><th>浏览 / 访客</th><th>IP 名额</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="row in records" :key="row.id">
                  <td><input v-model="selected" type="checkbox" :disabled="busy" :value="row.id" :aria-label="'选择 ' + row.filename"></td>
                  <td><strong :title="row.filename">{{ row.filename }}</strong><small>{{ formatDate(row.created_at) }}</small><small v-if="row.path_note" :title="row.path_note">{{ row.path_note }}</small></td>
                  <td v-if="admin">{{ row.owner }}</td>
                  <td>{{ row.agent_name || ({ web: '网页版', cli: 'CLI', unknown: '—' }[row.source]) }}</td>
                  <td>{{ row.device_name || '—' }}</td>
                  <td><span class="status" :data-status="row.status">{{ statusLabels[row.status] }}</span></td>
                  <td>{{ row.status === 'paused' ? '待重新设置' : formatDate(row.expires_at) }}<small v-if="remaining(row)">{{ remaining(row) }}</small></td>
                  <td>{{ row.pv }} / {{ row.uv }}</td><td>{{ row.ip_count }} / {{ row.max_ips }}</td>
                  <td class="actions">
                    <button v-if="['active', 'paused'].includes(row.status)" @click="copyRecord(row)">复制链接</button>
                    <button v-if="row.status === 'active'" @click="showExpiry(row)">修改到期</button>
                    <button v-if="row.status === 'active'" @click="showOperation('pause', row)">暂停</button>
                    <button v-if="row.status === 'paused'" @click="showOperation('resume', row)">恢复</button>
                    <button v-if="['active', 'paused'].includes(row.status)" @click="showOperation('close', row)">关闭</button>
                    <button v-else @click="showOperation('delete', row)">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty"><strong>没有符合条件的记录</strong></div>
          <footer class="pagination">
            <span>共 {{ total }} 条 · 第 {{ displayedPage }} / {{ pageCount }} 页</span>
            <label>每页 <select v-model.number="pageSize" @change="findRecords"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select></label>
            <NButton :disabled="!offset || busy" @click="changePage(-1)">上一页</NButton>
            <NButton :disabled="displayedPage >= pageCount || busy" @click="changePage(1)">下一页</NButton>
          </footer>
        </section>

        <section v-if="page === 'new'" class="panel narrow">
          <form class="form" @submit.prevent="createPublish">
            <label>HTML 文件<input type="file" accept=".html,.htm,text/html" required @change="chooseFile"><small>支持 UTF-8，最大 {{ settings.max_upload_mb || 10 }} MB。</small></label>
            <ul v-if="compatibility.length" class="compatibility" aria-label="兼容性检查" aria-live="polite">
              <li v-for="warning in compatibility" :key="warning">{{ warning }}</li>
            </ul>
            <ExpiryFields v-model="expiry" :capped="Boolean(settings.max_days)" />
            <label>独立公网 IP 名额<input v-model.number="maxIps" type="number" min="1" max="10000" required></label>
            <label>路径备注（可选）<input v-model="pathNote" maxlength="4096"></label>
            <NButton type="primary" attr-type="submit" :loading="busy">发布预览</NButton>
          </form>
          <div v-if="result" class="result">
            <strong>发布成功</strong>
            <div class="result-link"><input :value="result.url" aria-label="预览链接" readonly @focus="$event.target.select()"><NButton @click="copy(result.url)">复制</NButton></div>
            <a :href="result.url" target="_blank" rel="noopener noreferrer">打开链接</a>
            <ul v-if="result.warnings.length"><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul>
          </div>
        </section>

        <section v-if="page === 'accounts'" class="panel table-scroll">
          <table>
            <thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in accounts" :key="row.id">
              <td>{{ row.username }}</td><td>{{ row.role === 'admin' ? '超级管理员' : '发布者' }}</td>
              <td>{{ row.disabled ? '已停用' : '启用' }}</td><td class="actions"><button @click="openAccount(row)">编辑</button><button v-if="row.disabled" @click="modal = { kind: 'delete-account', row }">删除</button></td>
            </tr></tbody>
          </table>
        </section>

        <section v-if="page === 'devices'" class="panel table-scroll">
          <table v-if="devices.length">
            <thead><tr><th>设备</th><th>Agent 客户端</th><th>账号</th><th>最近使用</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in devices" :key="row.id">
              <td><strong>{{ row.device_name || '旧版授权 · ' + row.id.slice(0, 8) }}</strong><small>{{ row.device_model || '型号未提供' }}</small></td>
              <td>{{ row.agent_name || '—' }}</td><td>{{ row.username }}</td><td>{{ formatDate(row.last_used_at * 1000) }}</td>
              <td class="actions"><button @click="modal = { kind: 'device', row }">撤销</button></td>
            </tr></tbody>
          </table>
          <div v-else class="empty"><strong>没有有效的设备授权</strong></div>
        </section>

        <form v-if="page === 'settings'"  class="panel narrow form" @submit.prevent="saveSettings">
          <label>累计有效期上限（天）<input v-model="maxDays" type="number" min="1" max="36500" placeholder="不限"><small>留空表示不限制。修改后，现有链接保留原到期时间。</small></label>
          <ExpiryFields v-model="defaultExpiry" :capped="Boolean(maxDays)" preset-only legend="默认有效期" />
          <label v-for="[key, label, max] in policyFields" :key="key">{{ label }}<input v-model.number="settings[key]" type="number" min="1" :max="max" required></label>
          <NButton type="primary" attr-type="submit" :loading="busy">保存设置</NButton>
        </form>
      </main>

      <dialog ref="dialog" aria-label="WispLink 操作" @cancel="busy && $event.preventDefault()" @close="modal = null">
        <div v-if="modal" class="dialog-inner">
          <p v-if="error" class="error" role="alert">{{ error }}</p>
          <form v-if="modal.kind === 'expiry'" class="form" @submit.prevent="updateRecord">
            <h2>修改到期时间</h2><p>{{ modal.row.filename }}</p>
            <ExpiryFields v-model="editor" :capped="Boolean(settings.max_days)" />
            <small v-if="editor.mode === 'preset'">预设时长从现在开始计算。</small>
            <div class="dialog-actions"><NButton @click="modal = null">取消</NButton><NButton attr-type="submit" type="primary" :loading="busy">保存</NButton></div>
          </form>
          <form v-else-if="modal.kind === 'resume'" class="form" @submit.prevent="updateRecord">
            <h2>恢复发布</h2><p>{{ modal.row ? modal.row.filename : '对选中的 ' + selected.length + ' 条发布使用相同设置' }}</p>
            <ExpiryFields v-model="editor" :capped="Boolean(settings.max_days)" />
            <label>独立公网 IP 名额<input v-model.number="resumeIps" type="number" min="1" max="10000" placeholder="请重新输入 IP 名额" required></label>
            <small>原有 IP 记录继续计入新名额。恢复后沿用原链接。</small>
            <div class="dialog-actions"><NButton :disabled="busy" @click="modal = null">取消</NButton><NButton attr-type="submit" type="primary" :loading="busy">恢复发布</NButton></div>
          </form>
          <form v-else-if="modal.kind === 'account'" class="form" @submit.prevent="saveAccount">
            <h2>{{ modal.row ? '编辑账号' : '新建账号' }}</h2>
            <label>用户名<input v-model="account.username" maxlength="80" required></label>
            <label>{{ modal.row ? '新密码（可选）' : '密码' }}<input v-model="account.password" type="password" autocomplete="new-password" :required="!modal.row" minlength="12" maxlength="256"></label>
            <label class="check"><input v-model="account.admin" type="checkbox"> 超级管理员</label>
            <label v-if="modal.row" class="check"><input v-model="account.disabled" type="checkbox"> 停用账号</label>
            <div class="dialog-actions"><NButton @click="modal = null">取消</NButton><NButton attr-type="submit" type="primary" :loading="busy">保存</NButton></div>
          </form>
          <form v-else-if="modal.kind === 'password'" class="form" @submit.prevent="changePassword">
            <h2>修改密码</h2>
            <label>当前密码<input v-model="changedPassword.current" type="password" autocomplete="current-password" required></label>
            <label>新密码<input v-model="changedPassword.replacement" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label>
            <p>保存后需要重新登录并授权 CLI。</p>
            <div class="dialog-actions"><NButton @click="modal = null">取消</NButton><NButton attr-type="submit" type="primary" :loading="busy">保存</NButton></div>
          </form>
          <form v-else-if="modal.kind === 'delete-account'" class="form" @submit.prevent="deleteAccount">
            <h2>删除账号？</h2><p>将删除 {{ modal.row.username }} 的登录信息，保留发布记录和链接状态。</p>
            <div class="dialog-actions"><NButton @click="modal = null">取消</NButton><NButton attr-type="submit" type="error" :loading="busy">删除账号</NButton></div>
          </form>
          <form v-else-if="modal.kind === 'device'" class="form" @submit.prevent="revokeDevice">
            <h2>撤销设备授权？</h2><p>这台设备需要重新登录才能发布。</p>
            <div class="dialog-actions"><NButton @click="modal = null">取消</NButton><NButton attr-type="submit" type="error" :loading="busy">撤销</NButton></div>
          </form>
          <div v-else-if="modal.kind === 'link'"  class="form">
            <h2>预览链接</h2><input :value="modal.url" aria-label="预览链接" readonly @focus="$event.target.select()">
            <NButton @click="modal = null">完成</NButton>
          </div>
          <form v-else class="form" @submit.prevent="updateRecord">
            <h2>{{ operationLabels[modal.kind] }}？</h2>
            <p>{{ modal.row ? modal.row.filename : '已选择 ' + selected.length + ' 条发布' }}</p>
            <small>{{ { pause: '链接将暂停访问，服务器会保留 HTML。', close: '链接将永久关闭，服务器会清理 HTML。', delete: '发布记录将永久删除。' }[modal.kind] }}</small>
            <div class="dialog-actions"><NButton :disabled="busy" @click="modal = null">取消</NButton><NButton attr-type="submit" :type="modal.kind === 'pause' ? 'primary' : 'error'" :loading="busy">{{ operationLabels[modal.kind] }}</NButton></div>
          </form>
        </div>
      </dialog>
    </div>
  </NConfigProvider>
</template>
