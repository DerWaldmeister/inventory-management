<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ money(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="sliderStep"
          :disabled="maxBudget <= 0"
        />
        <div class="budget-scale">
          <span>{{ money(0) }}</span>
          <span>{{ t('restocking.budgetMax', { amount: money(maxBudget) }) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ money(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ money(remainingBudget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.longestLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.leadTimeDays', { days: maxLeadTime }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ recommendations.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="successMessage" class="message success-message">
          <span>{{ successMessage }}</span>
          <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
        </div>
        <div v-if="submitError" class="message error-message">{{ submitError }}</div>

        <div v-if="forecasts.length === 0" class="empty-state">{{ t('restocking.noData') }}</div>
        <div v-else-if="recommendations.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineCost') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.supplier') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendations" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td class="num">{{ item.quantity.toLocaleString() }}</td>
                <td class="num">{{ money(item.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ money(item.lineCost) }}</strong></td>
                <td class="num">{{ t('restocking.leadTimeDays', { days: item.lead_time_days }) }}</td>
                <td>{{ item.supplier_name }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const successMessage = ref('')
    const submitError = ref('')

    // Amounts are USD internally; convert only for display
    const money = (amount, decimals = 0) => {
      return decimals > 0
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    const getGrowth = (item) => {
      if (!item.current_demand) return item.forecasted_demand > 0 ? Infinity : 0
      return (item.forecasted_demand - item.current_demand) / item.current_demand
    }

    // Items worth restocking, ranked by growth descending
    const candidates = computed(() => {
      return forecasts.value
        .filter(f => f.forecasted_demand > f.current_demand || f.trend !== 'decreasing')
        .map(f => ({
          ...f,
          quantity: f.forecasted_demand,
          lineCost: f.forecasted_demand * f.unit_cost
        }))
        .sort((a, b) => getGrowth(b) - getGrowth(a))
    })

    const maxBudget = computed(() => {
      const sum = candidates.value.reduce((acc, c) => acc + c.lineCost, 0)
      return Math.ceil(sum)
    })

    const sliderStep = computed(() => Math.max(1, Math.round(maxBudget.value / 100)))

    // Greedy: take whole lines in rank order, skipping lines that no longer fit
    const recommendations = computed(() => {
      const picked = []
      let running = 0
      for (const c of candidates.value) {
        if (running + c.lineCost <= budget.value) {
          picked.push(c)
          running += c.lineCost
        }
      }
      return picked
    })

    const totalCost = computed(() => recommendations.value.reduce((acc, r) => acc + r.lineCost, 0))
    const remainingBudget = computed(() => Math.max(0, budget.value - totalCost.value))
    const maxLeadTime = computed(() => {
      return recommendations.value.reduce((acc, r) => Math.max(acc, r.lead_time_days), 0)
    })

    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return ''
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value / 2)
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
        console.error('Load error:', err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      successMessage.value = ''
      submitError.value = ''
      try {
        const order = await api.createRestockOrder({
          items: recommendations.value.map(r => ({ sku: r.item_sku, quantity: r.quantity })),
          // Round up to whole cents so float drift never makes total exceed budget
          budget: Math.ceil(budget.value * 100) / 100
        })
        successMessage.value = t('restocking.success', {
          orderNumber: order.order_number,
          date: formatDate(order.estimated_delivery)
        })
      } catch (err) {
        const detail = err.response?.data?.detail
        submitError.value = t('restocking.submitFailed') + ': ' +
          (typeof detail === 'string' ? detail : err.message)
        console.error('Place order error:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadData)

    return {
      t,
      loading,
      error,
      forecasts,
      budget,
      maxBudget,
      sliderStep,
      recommendations,
      totalCost,
      remainingBudget,
      maxLeadTime,
      submitting,
      successMessage,
      submitError,
      money,
      translateProductName,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #0f172a;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.num {
  text-align: right;
}

.place-order-btn {
  padding: 0.5rem 1.25rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.message {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin: 1rem 1.5rem 0;
  padding: 0.75rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
}

.success-message {
  background: #d1fae5;
  color: #065f46;
}

.success-message a {
  color: #065f46;
  font-weight: 600;
  text-decoration: underline;
}

.error-message {
  background: #fee2e2;
  color: #991b1b;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.875rem;
}
</style>
