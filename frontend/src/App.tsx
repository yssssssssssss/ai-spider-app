import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import HomePage from './pages/HomePage';
import SearchPage from './pages/SearchPage';
import AdminRequests from './pages/AdminRequests';
import AdminTasks from './pages/AdminTasks';
import AdminDashboard from './pages/AdminDashboard';

function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: 12, borderBottom: '1px solid #ccc' }}>
        <Link to="/" style={{ marginRight: 12 }}>前台-需求</Link>
        <Link to="/search" style={{ marginRight: 12 }}>前台-检索</Link>
        <Link to="/admin" style={{ marginRight: 12 }}>后台-看板</Link>
        <Link to="/admin/requests" style={{ marginRight: 12 }}>后台-需求</Link>
        <Link to="/admin/tasks">后台-任务</Link>
      </nav>
      <div style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/admin/requests" element={<AdminRequests />} />
          <Route path="/admin/tasks" element={<AdminTasks />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
