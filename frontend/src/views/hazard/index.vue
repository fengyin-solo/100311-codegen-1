<template>
  <section class="page" data-module="hazard">
    <header class="page-head">
      <div>
        <h2>隐患排查整改台账</h2>
        <p class="page-desc">
          一条隐患从登记起只能按「待整改 → 整改中 → 待复查 → 已销号」顺向推进；无复查结论不得销号，已销号不得退回。
          重复登记自动并入最早记录，超期未整改自动升矿级督办。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate(false)">登记隐患</button>
        <button class="btn" type="button" @click="openCreate(true)">补录存量</button>
        <button class="btn" type="button" @click="exportRows">导出台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ 'stat-warn': item.label === '超期未整改' && item.value > 0, 'stat-sup': item.label === '矿级督办' && item.value > 0 }">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="隐患编号 / 内容 / 地点" />
      </label>
      <label class="filter-item">
        <span>状态</span>
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
          <th>隐患编号</th>
          <th>隐患内容</th>
          <th>发现地点</th>
          <th>等级</th>
          <th>责任单位</th>
          <th>发现日期</th>
          <th>整改期限</th>
          <th>当前状态</th>
          <th>补充</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['隐患编号'] }}</td>
          <td class="cell-content">{{ row['隐患内容'] }}</td>
          <td>{{ row['发现地点'] }}</td>
          <td>
            <span class="badge" :class="levelClass(String(row['隐患等级']))">{{ row['隐患等级'] }}</span>
          </td>
          <td>{{ row['责任单位'] }}<span class="muted-text" v-if="row['责任人']"> / {{ row['责任人'] }}</span></td>
          <td>{{ row['发现日期'] }}<span v-if="row['补录']" class="tag tag-backfill">补录</span></td>
          <td>
            {{ row['整改期限'] || '—' }}
            <span v-if="isOverdue(row)" class="tag tag-overdue">已超期</span>
          </td>
          <td>
            <span class="badge" :class="statusClass(String(row.status))">{{ row.status }}</span>
            <RouterLink v-if="row['督办编号']" class="tag tag-sup" :to="{ path: '/supervision', query: { keyword: row['隐患编号'] } }">
              {{ row['督办编号'] }}
            </RouterLink>
          </td>
          <td>{{ (row['补充记录'] || []).length }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">台账</button>
            <button v-if="row.status === '待整改'" class="link" type="button" @click="openMeasures(row)">开始整改</button>
            <button v-if="row.status === '整改中'" class="link" type="button" @click="runAction(row, '整改完成')">申请复查</button>
            <button v-if="row.status === '待复查'" class="link" type="button" @click="openReview(row)">登记复查</button>
            <span v-if="row.status === '已销号'" class="muted-text">已归档</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="10" class="empty-state">暂无符合条件的隐患记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条隐患（重复登记已并入主记录，不单独建行）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <!-- 登记 / 补录 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>{{ form.backfill ? '按发现日期补录存量隐患' : '登记隐患' }}</h3>
        <p class="modal-tip" v-if="form.backfill">
          补录用于存量纸质台账入库：历史销号记录须按当时复查结论原样填写，系统不按新口径改写。
        </p>
        <div class="form-grid">
          <label><span>隐患内容 *</span><textarea v-model="form['隐患内容']" rows="2"></textarea></label>
          <label><span>发现地点 *</span><input v-model="form['发现地点']" placeholder="如：1203回风巷" /></label>
          <label><span>隐患等级</span>
            <select v-model="form['隐患等级']">
              <option>一般隐患</option><option>较大隐患</option><option>重大隐患</option>
            </select>
          </label>
          <label><span>责任单位 *</span><input v-model="form['责任单位']" placeholder="必须落到具体单位" /></label>
          <label><span>责任人</span><input v-model="form['责任人']" /></label>
          <label><span>发现人</span><input v-model="form['发现人']" /></label>
          <label><span>发现日期 *</span><input v-model="form['发现日期']" type="date" /></label>
          <label><span>整改期限</span><input v-model="form['整改期限']" type="date" /></label>
          <label class="full"><span>整改措施</span><textarea v-model="form['整改措施']" rows="2"></textarea></label>
          <template v-if="form.backfill">
            <label><span>登记时状态 *</span>
              <select v-model="form['状态']">
                <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
              </select>
            </label>
            <template v-if="form['状态'] === '已销号'">
              <label><span>当时复查结论 *</span><input v-model="form['复查结论']" placeholder="按纸质复查记录原文填写" /></label>
              <label><span>复查人 *</span><input v-model="form['复查人']" /></label>
              <label><span>复查日期 *</span><input v-model="form['复查日期']" type="date" /></label>
            </template>
          </template>
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">{{ form.backfill ? '确认补录' : '登记' }}</button>
        </div>
      </div>
    </div>

    <!-- 开始整改（可填措施） -->
    <div v-if="measuresOpen" class="modal-mask" @click.self="measuresOpen = false">
      <div class="modal modal-sm">
        <h3>开始整改</h3>
        <label class="block-label"><span>整改措施</span>
          <textarea v-model="measuresText" rows="3" placeholder="补充本次整改采取的措施（可选）"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="measuresOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitMeasures">确认开始整改</button>
        </div>
      </div>
    </div>

    <!-- 复查 -->
    <div v-if="reviewOpen" class="modal-mask" @click.self="reviewOpen = false">
      <div class="modal modal-sm">
        <h3>登记复查结论 · {{ reviewRow?.['隐患编号'] }}</h3>
        <p class="modal-tip">复查「合格」方可销号；「不合格」退回整改中重新整改。没有复查结论不能销号。</p>
        <label class="block-label"><span>复查结论 *</span>
          <select v-model="reviewForm['复查结论']">
            <option value="">请选择</option>
            <option value="合格">合格（准予销号）</option>
            <option value="不合格">不合格（退回整改）</option>
          </select>
        </label>
        <label class="block-label"><span>复查人 *</span><input v-model="reviewForm['复查人']" /></label>
        <label class="block-label"><span>复查日期</span><input v-model="reviewForm['复查日期']" type="date" /></label>
        <p v-if="reviewError" class="error-text">{{ reviewError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="reviewOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitReview">提交复查</button>
        </div>
      </div>
    </div>

    <!-- 台账详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-lg">
        <h3>隐患台账 · {{ detail['隐患编号'] }}</h3>
        <div class="detail-head">
          <span class="badge" :class="statusClass(String(detail.status))">{{ detail.status }}</span>
          <span v-if="detail['补录']" class="tag tag-backfill">存量补录</span>
          <RouterLink v-if="detail['督办编号']" class="tag tag-sup" :to="{ path: '/supervision', query: { keyword: detail['隐患编号'] } }">
            矿级督办：{{ detail['督办编号'] }}
          </RouterLink>
        </div>
        <dl class="detail-grid">
          <div><dt>隐患内容</dt><dd>{{ detail['隐患内容'] }}</dd></div>
          <div><dt>发现地点</dt><dd>{{ detail['发现地点'] }}</dd></div>
          <div><dt>隐患等级</dt><dd>{{ detail['隐患等级'] }}</dd></div>
          <div><dt>责任单位 / 责任人</dt><dd>{{ detail['责任单位'] }} / {{ detail['责任人'] || '—' }}</dd></div>
          <div><dt>发现人 / 发现日期</dt><dd>{{ detail['发现人'] || '—' }} / {{ detail['发现日期'] }}</dd></div>
          <div><dt>整改期限</dt><dd>{{ detail['整改期限'] || '—' }}</dd></div>
          <div><dt>整改措施</dt><dd>{{ detail['整改措施'] || '—' }}</dd></div>
          <div><dt>复查结论</dt><dd>{{ detail['复查结论'] || '—' }}<span v-if="detail['复查人']" class="muted-text">（{{ detail['复查人'] }} / {{ detail['复查日期'] }}）</span></dd></div>
          <div><dt>销号日期</dt><dd>{{ detail['销号日期'] || '—' }}</dd></div>
        </dl>

        <h4 class="detail-sub">补充记录（重复登记并入，{{ (detail['补充记录'] || []).length }} 条）</h4>
        <ul class="supplement-list">
          <li v-for="(s, idx) in detail['补充记录']" :key="idx">
            <span class="muted-text">{{ s['发现日期'] }} · {{ s['来源编号'] }}<span v-if="s['补录']" class="tag tag-backfill">补录</span></span>
            {{ s['补充内容'] }}
          </li>
          <li v-if="!(detail['补充记录'] || []).length" class="muted-text">无</li>
        </ul>

        <h4 class="detail-sub">流转记录</h4>
        <ol class="timeline">
          <li v-for="(e, idx) in detail.timeline" :key="idx">
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

const ENDPOINT = '/api/hazard'
const statuses = ['待整改', '整改中', '待复查', '已销号']

type Row = Record<string, any>
type Stat = { label: string; value: number }

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stat[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = reactive<Record<string, string>>({ keyword: '', status: '', unit: '' })
const route = useRoute()

function isOverdue(row: Row): boolean {
  if (row.status === '已销号' || !row['整改期限']) return false
  return String(row['整改期限']) < new Date().toISOString().slice(0, 10)
}

function statusClass(status: string): string {
  return { 待整改: 'badge-danger', 整改中: 'badge-warn', 待复查: 'badge-info', 已销号: 'badge-ok' }[status] || ''
}
function levelClass(level: string): string {
  return { 重大隐患: 'badge-danger', 较大隐患: 'badge-warn', 一般隐患: 'badge-info' }[level] || ''
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
    if (!response.ok) throw new Error('隐患台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隐患台账读取失败'
  }
  try {
    const res = await request(`${ENDPOINT}/stats`)
    if (res.ok) stats.value = (await res.json()).items ?? []
  } catch {
    /* 指标卡失败不阻塞列表 */
  }
}

async function postAction(path: string, body: Record<string, any>): Promise<{ ok: boolean; message: string; entry?: Row }> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return await response.json()
}

// ---------- 登记 / 补录 ----------
const createOpen = ref(false)
const createError = ref('')
const emptyForm = (): Row => ({
  backfill: false, '隐患内容': '', '发现地点': '', '隐患等级': '一般隐患',
  '责任单位': '', '责任人': '', '发现人': '', '发现日期': '', '整改期限': '',
  '整改措施': '', '状态': '待整改', '复查结论': '', '复查人': '', '复查日期': '',
})
const form = reactive<Row>(emptyForm())

function openCreate(backfill: boolean) {
  createError.value = ''
  Object.assign(form, emptyForm(), { backfill })
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  const result = await postAction(ENDPOINT, { values: { ...form } })
  if (!result.ok) {
    createError.value = result.message
    return
  }
  createOpen.value = false
  noticeMessage.value = result.message
  setTimeout(() => (noticeMessage.value = ''), 5000)
  await reload()
}

// ---------- 开始整改 ----------
const measuresOpen = ref(false)
const measuresText = ref('')
const measuresRow = ref<Row | null>(null)

function openMeasures(row: Row) {
  measuresRow.value = row
  measuresText.value = ''
  measuresOpen.value = true
}

async function submitMeasures() {
  if (!measuresRow.value) return
  const result = await postAction(`${ENDPOINT}/${measuresRow.value.id}/actions`, {
    values: { action: '开始整改', 整改措施: measuresText.value },
  })
  measuresOpen.value = false
  if (!result.ok) errorMessage.value = result.message
  await reload()
}

// ---------- 复查 ----------
const reviewOpen = ref(false)
const reviewError = ref('')
const reviewRow = ref<Row | null>(null)
const reviewForm = reactive({ 复查结论: '', 复查人: '', 复查日期: '' })

function openReview(row: Row) {
  reviewRow.value = row
  reviewError.value = ''
  reviewForm.复查结论 = ''
  reviewForm.复查人 = ''
  reviewForm.复查日期 = new Date().toISOString().slice(0, 10)
  reviewOpen.value = true
}

async function submitReview() {
  if (!reviewRow.value) return
  const result = await postAction(`${ENDPOINT}/${reviewRow.value.id}/actions`, {
    values: { action: '复查', ...reviewForm },
  })
  if (!result.ok) {
    reviewError.value = result.message
    return
  }
  reviewOpen.value = false
  await reload()
}

async function runAction(row: Row, action: string) {
  errorMessage.value = ''
  const result = await postAction(`${ENDPOINT}/${row.id}/actions`, { values: { action } })
  if (!result.ok) errorMessage.value = result.message
  await reload()
}

// ---------- 详情 ----------
const detail = ref<Row | null>(null)

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('台账明细读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '台账明细读取失败'
  }
}

onMounted(() => {
  if (typeof route.query.keyword === 'string') filters.keyword = route.query.keyword
  void reload()
})
</script>
