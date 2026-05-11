import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { getUser, updateUser } from '../utils/auth'
import { getEnabledModulesForIndustry, INDUSTRY_TYPES, resolveIndustryKey, resolveIndustryCode, hasIndustryFeature } from '../config/industryModules'
import api from '../services/apiClient'

const STORAGE_KEY = 'industry_type'

/**
 * Hook لإدارة نوع النشاط التجاري
 * يقرأ من localStorage + user object، ويحفظ في الـ Backend عبر API
 * 
 * ملاحظة: يُخزّن في localStorage والـ state بصيغة Key (RT, FB, MF)
 * ويُرسل إلى الباك اند بصيغة Code (retail, restaurant, manufacturing)
 */
export function useIndustryType() {
  const { t } = useTranslation()
  const [industryType, setIndustryTypeState] = useState(() => {
    // أولوية 1: localStorage cache
    const cached = localStorage.getItem(STORAGE_KEY)
    if (cached) {
      // Handle both key (RT) and code (retail) formats
      const key = resolveIndustryKey(cached)
      if (INDUSTRY_TYPES[key]) return key
    }

    // أولوية 2: user object من الـ token
    const user = getUser()
    if (user?.industry_type) {
      const key = resolveIndustryKey(user.industry_type)
      if (INDUSTRY_TYPES[key]) {
        localStorage.setItem(STORAGE_KEY, key)
        return key
      }
    }

    return null
  })

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // التحقق من وجود نوع النشاط
  const hasIndustryType = !!industryType

  // الوحدات المفعّلة بناءً على النشاط الحالي
  const enabledModules = industryType
    ? getEnabledModulesForIndustry(industryType)
    : []

  // معلومات النشاط الحالي
  const currentIndustry = industryType ? INDUSTRY_TYPES[industryType] : null

  /**
   * حفظ نوع النشاط في الـ Backend + localStorage + user object
   * @param {string} newType - Key format (RT, FB, MF) or Code format (retail, restaurant)
   */
  const setIndustryType = useCallback(async (newType) => {
    // Normalize to key for internal use
    const key = resolveIndustryKey(newType)
    if (!INDUSTRY_TYPES[key]) {
      setError(t('errors.invalid_industry_type'))
      return false
    }

    // Convert to code for backend storage
    const code = resolveIndustryCode(newType)

    setLoading(true)
    setError(null)

    try {
      const modules = getEnabledModulesForIndustry(key)

      // حفظ في company_settings — بصيغة code (retail, restaurant, etc.)
      await api.post('/settings/bulk', {
        settings: {
          industry_type: code
        }
      })

      // تحديث enabled_modules في الـ backend
      await api.put('/companies/modules', modules)

      // تحديث localStorage — بصيغة key (RT, FB, etc.)
      localStorage.setItem(STORAGE_KEY, key)

      // تحديث user object
      updateUser({
        industry_type: key,
        enabled_modules: modules
      })

      setIndustryTypeState(key)
      return true
    } catch (err) {
      console.error('Failed to save industry type:', err)
      setError(err.response?.data?.detail || t('errors.failed_save_industry_type'))
      return false
    } finally {
      setLoading(false)
    }
  }, [t])

  /**
   * تحميل نوع النشاط من الـ Backend (يُستخدم عند الحاجة)
   * الباك اند يُعيد code format (retail, restaurant) — نحوّله إلى key (RT, FB)
   */
  const fetchIndustryType = useCallback(async () => {
    try {
      const res = await api.get('/settings/')
      const serverType = res.data?.industry_type

      if (serverType) {
        // Backend returns code name (retail, restaurant, etc.) — convert to key
        const key = resolveIndustryKey(serverType)
        if (INDUSTRY_TYPES[key]) {
          localStorage.setItem(STORAGE_KEY, key)
          setIndustryTypeState(key)
          return key
        }
      }
      return null
    } catch (err) {
      console.error('Failed to fetch industry type:', err)
      return null
    }
  }, [])

  // مزامنة مع الـ backend عند أول تحميل
  useEffect(() => {
    if (!industryType) {
      fetchIndustryType()
    }
  }, [industryType, fetchIndustryType])

  return {
    industryType,
    hasIndustryType,
    currentIndustry,
    enabledModules,
    setIndustryType,
    fetchIndustryType,
    loading,
    error,
  }
}

/**
 * التحقق السريع من وجود نوع النشاط (بدون hook)
 * يُستخدم في الأماكن التي لا يمكن استخدام hooks فيها
 */
export function hasIndustryTypeSet() {
  const cached = localStorage.getItem(STORAGE_KEY)
  if (cached) {
    const key = resolveIndustryKey(cached)
    if (INDUSTRY_TYPES[key]) return true
  }

  const user = getUser()
  if (user?.industry_type) {
    const key = resolveIndustryKey(user.industry_type)
    return !!INDUSTRY_TYPES[key]
  }
  return false
}

/**
 * الحصول على نوع النشاط الحالي (بدون hook)
 * يُعيد key format (RT, FB, MF)
 */
export function getIndustryType() {
  const cached = localStorage.getItem(STORAGE_KEY)
  if (cached) {
    const key = resolveIndustryKey(cached)
    if (INDUSTRY_TYPES[key]) return key
  }

  const user = getUser()
  if (user?.industry_type) {
    const key = resolveIndustryKey(user.industry_type)
    if (INDUSTRY_TYPES[key]) return key
  }

  return null
}

/**
 * تحقق (بدون hook) إذا كانت ميزة محددة متاحة للنشاط الحالي
 * @param {string} featureKey - مفتاح الميزة مثل 'pos.table_management'
 * @returns {boolean}
 */
export function getIndustryFeature(featureKey) {
  const industry = getIndustryType()
  return hasIndustryFeature(featureKey, industry)
}

export default useIndustryType
