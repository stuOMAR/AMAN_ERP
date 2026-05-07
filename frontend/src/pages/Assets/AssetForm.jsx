import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useForm, Controller } from 'react-hook-form';
import { assetsAPI, branchesAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { getCurrency } from '../../utils/auth';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { Save, Building, DollarSign, Calendar, Hash, Briefcase, MapPin } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { Spinner } from '../../components/common/LoadingStates'

const AssetForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { id } = useParams();
    const isEdit = !!id;
    const currency = getCurrency();
    const { register, handleSubmit, reset, control, formState: { errors } } = useForm();
    const [submitting, setSubmitting] = useState(false);
    const [branches, setBranches] = useState([]);

    useEffect(() => {
        fetchBranches();
        if (isEdit) {
            fetchAsset();
        }
    }, [id]);

    const fetchBranches = async () => {
        try {
            const res = await branchesAPI.list();
            setBranches(res.data);
        } catch (err) {
            console.error("Failed to load branches", err);
        }
    };

    const fetchAsset = async () => {
        try {
            const response = await assetsAPI.get(id);
            const assetData = response.data.asset;
            reset({
                ...assetData,
                purchase_date: assetData.purchase_date // CustomDatePicker expects YYYY-MM-DD string or Date object
            });
        } catch (error) {
            console.error("Failed to fetch asset", error);
            navigate('/assets');
        }
    };

    const onSubmit = async (data) => {
        setSubmitting(true);
        try {
            const payload = {
                ...data,
                cost: parseFloat(data.cost),
                residual_value: parseFloat(data.residual_value || 0),
                life_years: parseInt(data.life_years),
                branch_id: data.branch_id ? parseInt(data.branch_id) : null,
                depreciation_method: 'straight_line',
                currency: currency
            };

            if (isEdit) {
                await assetsAPI.update(id, payload);
                toastEmitter.emit(t('assets.updated_msg', 'Asset updated successfully'), 'success');
            } else {
                await assetsAPI.create(payload);
                toastEmitter.emit(t('assets.created_msg', 'Asset created successfully'), 'success');
            }
            navigate('/assets');
        } catch (error) {
            console.error("Save failed", error);
            toastEmitter.emit(t('common.error_occurred'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header mb-4">
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div className="d-flex align-items-center gap-3">
                        <BackButton />
                        <div>
                            <h1 className="workspace-title h3 mb-1 fw-bold">
                                {isEdit ? t('assets.edit', 'Edit Asset') : t('assets.new', 'New Fixed Asset')}
                            </h1>
                            <p className="workspace-subtitle mb-0 text-secondary">
                                {t('assets.subtitle', 'Manage company assets and depreciation')}
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            <div className="container-fluid py-2">
                <div className="row justify-content-center">
                    <div className="col-lg-10 col-xl-9">
                        <form onSubmit={handleSubmit(onSubmit)} className="row g-4">
                            {/* Left Column: Basic Info */}
                            {/* Single Centered Column */}
                            <div className="col-lg-8 mx-auto">
                                {/* Basic Info Card */}
                                <div className="card mb-4">
                                    <div >
                                        <div className="d-flex align-items-center mb-4 pb-2 border-bottom">
                                            <div className="bg-primary-subtle p-2 rounded-3 me-3 text-primary d-flex align-items-center justify-content-center" style={{ width: '42px', height: '42px' }}>
                                                <Building size={22} />
                                            </div>
                                            <h3 className="h5 mb-0 fw-bold">{t('common.basic_info', 'Basic Information')}</h3>
                                        </div>

                                        <div className="row g-4">
                                            <div className="col-12">
                                                <FormField label={<><Hash size={14} /> {t('assets.name', 'Asset Name')}</>} required>
                                                    <input
                                                        id="name"
                                                        className={`form-input ${errors.name ? 'is-invalid' : ''}`}
                                                        {...register('name', { required: true })}
                                                        placeholder={t('assets.name_placeholder', 'e.g. Server R-740')}
                                                    />
                                                </FormField>
                                            </div>

                                            <div className="col-md-6">
                                                <FormField label={<><Briefcase size={14} /> {t('assets.type', 'Asset Type')}</>} required>
                                                    <select
                                                        id="type"
                                                        className="form-select"
                                                        {...register('type', { required: true })}
                                                    >
                                                        <option value="tangible">{t('assets.types.tangible', 'Tangible (Hardware, Furniture)')}</option>
                                                        <option value="intangible">{t('assets.types.intangible', 'Intangible (Software, License)')}</option>
                                                    </select>
                                                </FormField>
                                            </div>

                                            <div className="col-md-6">
                                                <FormField label={<><MapPin size={14} /> {t('common.branch', 'Branch')}</>}>
                                                    <select
                                                        id="branch_id"
                                                        className="form-select"
                                                        {...register('branch_id')}
                                                    >
                                                        <option value="">{t('common.select_branch', 'Select Branch')}</option>
                                                        {branches.map(branch => (
                                                            <option key={branch.id} value={branch.id}>{branch.name}</option>
                                                        ))}
                                                    </select>
                                                </FormField>
                                            </div>

                                            <div className="col-12">
                                                <FormField label={<><Hash size={14} /> {t('assets.code', 'Asset Code')}</>}>
                                                    <input
                                                        id="code"
                                                        className="form-input"
                                                        {...register('code')}
                                                        placeholder={t('assets.code_placeholder', 'Auto-generated if empty')}
                                                    />
                                                </FormField>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* Financial Details Card */}
                                <div className="card">
                                    <div >
                                        <div className="d-flex align-items-center mb-4 pb-2 border-bottom">
                                            <div className="bg-success-subtle p-2 rounded-3 me-3 text-success d-flex align-items-center justify-content-center" style={{ width: '42px', height: '42px' }}>
                                                <DollarSign size={22} />
                                            </div>
                                            <h3 className="h5 mb-0 fw-bold">{t('assets.financials', 'Financial Details')}</h3>
                                        </div>

                                        <div className="row g-4">
                                            <div className="col-12">
                                                <Controller
                                                    control={control}
                                                    name="purchase_date"
                                                    rules={{ required: true }}
                                                    render={({ field }) => (
                                                        <CustomDatePicker
                                                            id="purchase_date"
                                                            label={<span className="d-flex align-items-center gap-2"><Calendar size={14} /> {t('assets.purchase_date', 'Purchase Date')}</span>}
                                                            selected={field.value}
                                                            onChange={(date) => field.onChange(date)}
                                                            required
                                                        />
                                                    )}
                                                />
                                            </div>

                                            <div className="col-12">
                                                <FormField label={<><DollarSign size={14} /> {t('assets.cost', 'Initial Cost')}</>} required>
                                                    <div className="input-group">
                                                        <input
                                                            id="cost"
                                                            type="number"
                                                            step="0.01"
                                                            className="form-input"
                                                            {...register('cost', { required: true })}
                                                        />
                                                        <span className="input-group-text">
                                                            {currency}
                                                        </span>
                                                    </div>
                                                </FormField>
                                            </div>


                                            <div className="col-12">
                                                <FormField label={<><Hash size={14} /> {t('assets.life_years', 'Useful Life (Years)')}</>} required>
                                                    <input
                                                        id="life_years"
                                                        type="number"
                                                        className="form-input"
                                                        {...register('life_years', { required: true, min: 1 })}
                                                    />
                                                </FormField>
                                            </div>

                                            <div className="col-12">
                                                <FormField label={<><DollarSign size={14} /> {t('assets.residual_value', 'Residual Value')}</>} hint={t('assets.residual_hint', 'Expected value at end of useful life')}>
                                                    <div className="input-group">
                                                        <input
                                                            id="residual_value"
                                                            type="number"
                                                            step="0.01"
                                                            className="form-input"
                                                            {...register('residual_value')}
                                                            defaultValue={0}
                                                        />
                                                        <span className="input-group-text">
                                                            {currency}
                                                        </span>
                                                    </div>
                                                </FormField>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Form Actions */}
                            <div className="col-12 mt-5">
                                <div className="d-flex gap-3 justify-content-end">
                                    <button
                                        type="button"
                                        className="btn btn-light px-5 py-2 fw-bold text-secondary border shadow-sm"
                                        onClick={() => navigate('/assets')}
                                        style={{ borderRadius: '12px' }}
                                    >
                                        {t('common.cancel')}
                                    </button>
                                    <button
                                        type="submit"
                                        className="btn btn-primary px-5 py-2 fw-bold shadow-sm d-flex align-items-center gap-2"
                                        disabled={submitting}
                                        style={{ borderRadius: '12px' }}
                                    >
                                        {submitting ? (
                                            <>
                                                <Spinner size="sm"/>
                                                {t('common.saving')}
                                            </>
                                        ) : (
                                            <>
                                                <Save size={20} />
                                                {t('common.save')}
                                            </>
                                        )}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            </div >
        </div >
    );
};

export default AssetForm;
