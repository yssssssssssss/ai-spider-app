import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createWatchPlan } from '../api';
import { useToast } from './Toast';

function localDateInputValue(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

const today = localDateInputValue();

const initialForm = {
  name: '',
  target_app: '淘宝',
  target_page: '',
  entry_instruction: '',
  focus_question: '',
  schedule_time: '10:00',
  schedule_cycle: 'daily',
  schedule_start_date: today,
  schedule_end_date: '',
};

export default function WatchPlanForm({ homePanel = false }: { homePanel?: boolean }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);

  const update = (key: string, value: string) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        name: form.name.trim(),
        target_app: form.target_app.trim(),
        target_page: form.target_page.trim(),
        entry_instruction: form.entry_instruction.trim(),
        focus_question: form.focus_question.trim() || null,
        schedule_time: form.schedule_time.length === 5 ? `${form.schedule_time}:00` : form.schedule_time,
        schedule_start_date: form.schedule_start_date || null,
        schedule_end_date: form.schedule_end_date || null,
      };
      const { data } = await createWatchPlan(payload);
      showToast('观察计划已创建', 'success');
      navigate(`/admin/watch-plans/${data.id}`);
    } catch {
      // API 拦截器会提示错误
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`watch-form${homePanel ? ' animate-fade-in-scale home-watch-form' : ''}`}>
      {homePanel && (
        <div>
          <h2 style={{ marginBottom: 8 }}>新建观察</h2>
          <p style={{ marginBottom: 32, color: 'var(--text-secondary)' }}>
            创建一个按周期自动采集的固定页面首屏观察计划
          </p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="form-grid">
          <label>
            <span>观察名称</span>
            <input
              value={form.name}
              onChange={event => update('name', event.target.value)}
              placeholder="淘宝百亿补贴日常观察"
              required
            />
          </label>
          <label>
            <span>目标 App</span>
            <input
              value={form.target_app}
              onChange={event => update('target_app', event.target.value)}
              placeholder="淘宝"
              required
            />
          </label>
          <label>
            <span>目标页面</span>
            <input
              value={form.target_page}
              onChange={event => update('target_page', event.target.value)}
              placeholder="百亿补贴"
              required
            />
          </label>
          <label>
            <span>执行时间</span>
            <input
              type="time"
              value={form.schedule_time}
              onChange={event => update('schedule_time', event.target.value)}
              required
            />
          </label>
          <label>
            <span>执行周期</span>
            <select
              value={form.schedule_cycle}
              onChange={event => update('schedule_cycle', event.target.value)}
              required
            >
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
          </label>
          <label>
            <span>开始日期</span>
            <input
              type="date"
              value={form.schedule_start_date}
              onChange={event => update('schedule_start_date', event.target.value)}
              required
            />
          </label>
          <label>
            <span>结束日期</span>
            <input
              type="date"
              value={form.schedule_end_date}
              onChange={event => update('schedule_end_date', event.target.value)}
            />
          </label>
        </div>

        <label>
          <span>进入路径</span>
          <textarea
            value={form.entry_instruction}
            onChange={event => update('entry_instruction', event.target.value)}
            placeholder="打开淘宝，从首页进入百亿补贴，等待页面加载完成"
            required
          />
        </label>

        <label>
          <span>关注问题</span>
          <textarea
            value={form.focus_question}
            onChange={event => update('focus_question', event.target.value)}
            placeholder="关注页面的补贴利益点、主视觉、频道入口和活动氛围变化"
          />
        </label>

        <div className="form-actions">
          <button type="submit" disabled={submitting}>
            {submitting ? '创建中...' : '创建观察计划'}
          </button>
        </div>
      </form>
    </div>
  );
}
