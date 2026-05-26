import { useState } from 'react';
import { searchImages } from '../api';
import ImageCard from './ImageCard';

export default function SearchBox() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);

  const handleSearch = async () => {
    const { data } = await searchImages({ query, limit: 20 });
    setResults(data);
  };

  return (
    <div>
      <h2>自然语言检索竞品图片</h2>
      <div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="输入描述，如红色大促弹窗设计" />
        <button onClick={handleSearch}>搜索</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {results.map((r, i) => <ImageCard key={i} result={r} />)}
      </div>
    </div>
  );
}
