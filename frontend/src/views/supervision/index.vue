<template>
  <section class="page" data-module="supervision">
    <header class="page-head">
      <div>
        <h2>矿级督办清单</h2>
        <p class="page-desc">
          超期未整改的隐患自动升办后在本清单单独排一行；复查结论与销号回写待办清单，办理进度随隐患台账一起变化。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出督办清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ 'stat-warn': item.label === '超期办理' && item.value > 0 }">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="督办编号 / 隐患编号 / 内容" />
      </label>
      <label class="filter-item">
        <span>督办状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>责任单位</span>
        <input v-model="filters.unit" placeholder="如：通风队" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>督办编号</th>
          <th>隐患编号</th>
          <th>隐患内容</th>
          <th>责任单位</th>
          <th>升办日期</th>
          <th>整改期限</th>
          <th>办理进度</th>
          <th>督办状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['督办编号'] }}</td>
          <td>
            <RouterLink class="link" :to="{ path: '/hazard', query: { keyword: row['隐患编号'] } }">
              {{ row['隐患编号'] }}
            </RouterLink>
          </td>
          <td class="cell-content">{{ row['隐患内容'] }}</td>
          <td>{{ row['责任单位'] }}<span class="muted-text" v-if="row['责任人']"> / {{ row['责任人'] }}</span></td>
          <td>{{ row['升办日期'] }}</td>
          <td>
            {{ row['整改期限'] }}
            <span v-if="isOverdue(row)" class="tag tag-overdue">超期办理</span>
          </td>
          <td class="cell-content">{{ row['办理进度'] }}</td>
          <td><span class="badge" :class="statusClass(String(row.status))">{{ row.status }}</span></td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">待办清单</button>
            <button v-if="row.status !== '已销号'" class="link" type="button" @click="openUrge(row)">催办</button>
            <span v-else class="muted-text">已办结</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">暂无矿级督办事项</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条督办（超期隐患自动升办，无需手工登记）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 催办 -->
    <div v-if="urgeOpen" class="modal-mask" @click.self="urgeOpen = false">
      <div class="modal modal-sm">
        <h3>矿级催办 · {{ urgeRow?.['督办编号'] }}</h3>
        <label class="block-label"><span>催办说明</span>
          <textarea v-model="urgeNote" rows="3" placeholder="如：要求10月6日前完成整改并反馈措施"></textarea>
        </label>
        <p v-if="urgeError" class="error-text">{{ urgeError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="urgeOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitUrge">记入待办清单</button>
        </div>
      </div>
    </div>

    <!-- 督办待办清单 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-lg">
        <h3>督办待办 · {{ detail['督办编号'] }}</h3>
        <div class="detail-head">
          <span class="badge" :class="statusClass(String(detail.status))">{{ detail.status }}</span>
          <span class="muted-text">{{ detail['升办原因'] }}</span>
        </div>
        <dl class="detail-grid">
          <div><dt>隐患</dt><dd>{{ detail['隐患编号'] }} · {{ detail['隐患内容'] }}</dd></div>
          <div><dt>责任单位 / 责任人</dt><dd>{{ detail['责任单位'] }} / {{ detail['责任人'] || '—' }}</dd></div>
          <div><dt>升办日期 / 整改期限</dt><dd>{{ detail['升办日期'] }} / {{ detail['整改期限'] }}</dd></div>
          <div><dt>办理进度</dt><dd>{{ detail['办理进度'] }}</dd></div>
          <div v-if="detail['复查结论']"><dt>销号复查结论</dt><dd>{{ detail['复查结论'] }}<span class="muted-text">（{{ detail['复查人'] }} / {{ detail['复查日期'] }}）</span></dd></div>
          <div v-if="detail['销号日期']"><dt>办结日期</dt><dd>{{ detail['销号日期'] }}</dd></div>
        </dl>
        <h4 class="detail-sub">待办清单（随隐患台账自动回写）</h4>
        <ol class="timeline">
          <li v-for="(e, idx) in detail['待办清单']" :key="idx">
            <span class="timeline-date">{{ e['日期'] }}</span>
            <strong>{{ e['事项'] }}</strong>
            <span class="muted-text">{{ e['说明'] }}</span>
          </li>
        </ol>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

const ENDPOINT = '/api/supervision'
const statuses = ['跟踪整改', '待复查', '已销号']

type Row = Record<string, any>
type Stat = { label: string; value: number }

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stat[]>([])
const errorMessage = ref('')
const filters = reactive<Record<string, string>>({ keyword: '', status: '', unit: '' })
const route = useRoute()

function isOverdue(row: Row): boolean {
  if (row.status === '已销号' || !row['整改期限']) return false
  return String(row['整改期限']) < new Date().toISOString().slice(0, 10)
}

function statusClass(status: string): string {
  return { 跟踪整改: 'badge-danger', 待复查: 'badge-info', 已销号: 'badge-ok' }[status] || ''
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.unit = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.status) params.set('status', filters.status)
  if (filters.unit) params.set('unit', filters.unit)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('督办清单读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '督办清单读取失败'
  }
  try {
    const res = await request(`${ENDPOINT}/stats`)
    if (res.ok) stats.value = (await res.json()).items ?? []
  } catch {
    /* 指标卡失败不阻塞列表 */
  }
}

// ---------- 催办 ----------
const urgeOpen = ref(false)
const urgeError = ref('')
const urgeNote = ref('')
const urgeRow = ref<Row | null>(null)

function openUrge(row: Row) {
  urgeRow.value = row
  urgeNote.value = ''
  urgeError.value = ''
  urgeOpen.value = true
}

async function submitUrge() {
  if (!urgeRow.value) return
  urgeError.value = ''
  const response = await request(`${ENDPOINT}/${urgeRow.value.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action: '催办', 说明: urgeNote.value } }),
  })
  const result = await response.json()
  if (!result.ok) {
    urgeError.value = result.message
    return
  }
  urgeOpen.value = false
  await reload()
}

// ---------- 待办详情 ----------
const detail = ref<Row | null>(null)

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('督办明细读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '督办明细读取失败'
  }
}

onMounted(() => {
  if (typeof route.query.keyword === 'string') filters.keyword = route.query.keyword
  void reload()
})
</script>
