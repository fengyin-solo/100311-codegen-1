<template>
  <section class="page" data-module="hazard">
    <header class="page-head">
      <div>
        <h2>隐患排查整改台账</h2>
        <p class="page-desc">隐患从登记到销号全程流转：状态只能按待整改→整改中→待复查→已销号顺序走，超期未整改自动升矿级督办。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showForm = !showForm">{{ showForm ? '收起登记' : '登记隐患' }}</button>
        <button class="btn" type="button" @click="exportRows">导出隐患台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showForm" class="filter-bar create-panel" @submit.prevent="submitCreate">
      <label class="filter-item">
        <span>隐患地点 *</span>
        <input v-model="form.隐患地点" placeholder="如：1102综采工作面" />
      </label>
      <label class="filter-item">
        <span>隐患内容 *</span>
        <input v-model="form.隐患内容" placeholder="隐患具体表现" />
      </label>
      <label class="filter-item">
        <span>责任单位 *</span>
        <input v-model="form.责任单位" placeholder="落到具体责任单位" />
      </label>
      <label class="filter-item">
        <span>隐患等级</span>
        <select v-model="form.隐患等级">
          <option v-for="level in levels" :key="level" :value="level">{{ level }}</option>
        </select>
      </label>
      <template v-if="!form.补录">
        <label class="filter-item">
          <span>登记人 *</span>
          <input v-model="form.登记人" placeholder="谁登记的" />
        </label>
        <label class="filter-item">
          <span>整改期限 *</span>
          <input v-model="form.整改期限" type="date" />
        </label>
        <label class="filter-item">
          <span>整改措施</span>
          <input v-model="form.整改措施" placeholder="整改要求与措施" />
        </label>
      </template>
      <template v-else>
        <label class="filter-item">
          <span>发现日期 *</span>
          <input v-model="form.发现日期" type="date" />
        </label>
        <label class="filter-item">
          <span>历史状态</span>
          <select v-model="form.历史状态">
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>复查结论（历史销号必填）</span>
          <input v-model="form.复查结论" placeholder="按当时纸质记录原样填写" />
        </label>
        <label class="filter-item">
          <span>销号日期</span>
          <input v-model="form.销号日期" type="date" />
        </label>
      </template>
      <label class="filter-item">
        <span>存量补录</span>
        <input v-model="form.补录" type="checkbox" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>补充记录</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ supplementCount(row) ? `${supplementCount(row)} 条` : '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length">已归档</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无隐患记录，可先登记隐患</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">矿级督办清单（超期未整改自动升入）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in supervisionColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in supervision" :key="String(item.督办编号)">
          <td v-for="column in supervisionColumns" :key="column">{{ item[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!supervision.length">
          <td :colspan="supervisionColumns.length" class="empty-state">当前没有超期督办的隐患</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条隐患记录 · 督办 {{ supervision.length }} 条</span>
      <span v-if="message" :class="messageOk ? '' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/hazard'
const columns = ['隐患编号', '发现日期', '隐患地点', '隐患内容', '责任单位', '整改期限', '状态']
const supervisionColumns = ['督办编号', '隐患编号', '隐患内容', '责任单位', '整改期限', '超期天数', '督办等级', '进度', '销号结论']
const statuses = ['待整改', '整改中', '待复查', '已销号']
const levels = ['一般', '较大', '重大']
const nextAction: Record<string, string> = { 待整改: '开始整改', 整改中: '整改完成', 待复查: '复查销号' }

const rows = ref<Row[]>([])
const supervision = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: '待整改', value: 0 }, { label: '整改中', value: 0 }, { label: '待复查', value: 0 }, { label: '矿级督办', value: 0 }])
const message = ref('')
const messageOk = ref(false)
const showForm = ref(false)
const filters = ref<Record<string, string>>({})
const filterFields = ['隐患内容', '责任单位']
const emptyForm = { 隐患地点: '', 隐患内容: '', 责任单位: '', 隐患等级: '一般', 登记人: '', 整改期限: '', 整改措施: '', 补录: false, 发现日期: '', 历史状态: '已销号', 复查结论: '', 销号日期: '' }
const form = ref({ ...emptyForm })

function rowActions(row: Row) {
  const action = nextAction[String(row.status)]
  return action ? [action] : []
}

function supplementCount(row: Row) {
  return Array.isArray(row.supplements) ? row.supplements.length : 0
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  message.value = ''
  const values: Record<string, unknown> = {
    隐患地点: form.value.隐患地点,
    隐患内容: form.value.隐患内容,
    责任单位: form.value.责任单位,
    隐患等级: form.value.隐患等级,
  }
  if (form.value.补录) {
    values.登记方式 = '存量补录'
    values.发现日期 = form.value.发现日期
    values.历史状态 = form.value.历史状态
    values.复查结论 = form.value.复查结论
    values.销号日期 = form.value.销号日期
  } else {
    values.登记人 = form.value.登记人
    values.整改期限 = form.value.整改期限
    values.整改措施 = form.value.整改措施
  }
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json()
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message ?? (payload.ok ? '隐患已登记' : '隐患登记未生效')
    if (payload.ok) {
      form.value = { ...emptyForm }
      showForm.value = false
      await reload()
    }
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '隐患登记失败'
  }
}

async function runAction(action: string, row: Row) {
  message.value = ''
  const values: Record<string, unknown> = { action }
  if (action === '复查销号') {
    const conclusion = window.prompt(`请输入隐患 ${row.隐患编号} 的复查结论`)
    if (!conclusion || !conclusion.trim()) {
      messageOk.value = false
      message.value = '缺少复查结论，不得销号'
      return
    }
    values.复查结论 = conclusion.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message ?? '隐患动作未生效，请稍后重试'
    await reload()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '隐患操作失败'
  }
}

async function reload() {
  const query = new URLSearchParams()
  if (filters.value.隐患内容) query.set('keyword', filters.value.隐患内容)
  if (filters.value.责任单位) query.set('unit', filters.value.责任单位)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const [listResp, supResp] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/supervision`),
    ])
    if (!listResp.ok) throw new Error('隐患台账列表读取失败')
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (supResp.ok) {
      const supPayload = await supResp.json()
      supervision.value = supPayload.items ?? []
    }
    stats.value = [
      { label: '待整改', value: rows.value.filter((row) => row.status === '待整改').length },
      { label: '整改中', value: rows.value.filter((row) => row.status === '整改中').length },
      { label: '待复查', value: rows.value.filter((row) => row.status === '待复查').length },
      { label: '矿级督办', value: supervision.value.filter((item) => item.进度 !== '已办结').length },
    ]
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '隐患台账列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.create-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.section-title {
  font-size: 14px;
  margin: 16px 0 8px;
}
</style>
