import { Link } from 'react-router-dom';
import WatchPlanForm from '../components/WatchPlanForm';

export default function AdminWatchPlanNew() {
  return (
    <div className="animate-fade-in">
      <div className="page-header watch-header">
        <div>
          <h1>新建观察</h1>
          <p>创建一个每天自动采集的固定页面首屏观察计划</p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to="/admin/watch-plans">
          返回列表
        </Link>
      </div>

      <WatchPlanForm />
    </div>
  );
}
