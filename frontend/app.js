const API_BASE = 'http://127.0.0.1:8000';
const { useMemo, useState } = React;

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function getCategoryColor(key) {
  const palette = {
    open_source: '#3b82f6',
    self_projects: '#8b5cf6',
    production: '#10b981',
    technical_skills: '#f59e0b',
  };
  return palette[key] || '#64748b';
}

function CategoryMeter({ keyName, title, category, width }) {
  return React.createElement(
    'div',
    { className: 'meter-card' },
    React.createElement(
      'div',
      { className: 'meter-header' },
      React.createElement('span', null, title),
      React.createElement('b', null, `${category.score}/${category.max}`)
    ),
    React.createElement('div', { className: 'meter-track' },
      React.createElement('div', {
        className: 'meter-fill',
        style: {
          width: `${width}%`,
          background: getCategoryColor(keyName),
        },
      })
    ),
    React.createElement('div', { className: 'meter-evidence' }, category.evidence)
  );
}

function App() {
  const [pdfPath, setPdfPath] = useState('D:\\resume checker\\hiring-agent\\sde checking.pdf');
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const summary = useMemo(() => {
    if (!result || !result.evaluation) {
      return null;
    }

    const evalData = result.evaluation;
    const scoreEntries = Object.values(evalData.scores || {});
    const base = scoreEntries.reduce((total, item) => total + Math.min(item.score, item.max), 0);
    const bonus = Number(evalData.bonus_points?.total || 0);
    const deductions = Number(evalData.deductions?.total || 0);
    const total = Math.max(0, base + bonus - deductions);
    const max = scoreEntries.reduce((total, item) => total + item.max, 0) + 20;

    return {
      total,
      max,
      base,
      bonus,
      deductions,
      strengths: evalData.key_strengths || [],
      improvements: evalData.areas_for_improvement || [],
      categories: evalData.scores || {},
    };
  }, [result]);

  async function evaluateByPath() {
    if (!pdfPath.trim()) {
      setError('Please enter a PDF path first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const response = await fetch(`${API_BASE}/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_path: pdfPath }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Unknown evaluation error');
      }

      setResult(payload);
    } catch (err) {
      setError(err.message || 'Failed to evaluate PDF.');
    } finally {
      setLoading(false);
    }
  }

  async function evaluateUploadedFile() {
    if (!selectedFile) {
      setError('Please choose a PDF file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('uploaded_file', selectedFile);

    try {
      const response = await fetch(`${API_BASE}/evaluate-file`, {
        method: 'POST',
        body: formData,
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Unknown upload error');
      }

      setResult(payload);
    } catch (err) {
      setError(err.message || 'Failed to upload and evaluate PDF.');
    } finally {
      setLoading(false);
    }
  }

  const categoryEntries = summary?.categories
    ? Object.entries(summary.categories)
    : [];

  return React.createElement(
    'div',
    { className: 'app-shell' },
    React.createElement(
      'section',
      { className: 'panel left-panel' },
      React.createElement('h1', null, 'Resume Evaluator'),
      React.createElement(
        'p',
        { className: 'subtitle' },
        'Upload a PDF or provide a local resume path to score it with the hiring agent pipeline.'
      ),
      React.createElement(
        'div',
        { className: 'form-group' },
        React.createElement('label', null, 'Resume path'),
        React.createElement('input', {
          type: 'text',
          value: pdfPath,
          onChange: (e) => setPdfPath(e.target.value),
          placeholder: 'D:\\resume checker\\hiring-agent\\sde checking.pdf',
        })
      ),
      React.createElement(
        'button',
        { className: 'primary-button', onClick: evaluateByPath },
        loading ? 'Evaluating...' : 'Evaluate by path'
      ),
      React.createElement(
        'div',
        { className: 'form-group' },
        React.createElement('label', null, 'Upload PDF'),
        React.createElement('input', {
          type: 'file',
          accept: 'application/pdf',
          onChange: (e) => setSelectedFile(e.target.files[0]),
        })
      ),
      React.createElement(
        'button',
        { className: 'primary-button', onClick: evaluateUploadedFile },
        loading ? 'Uploading...' : 'Evaluate uploaded file'
      ),
      React.createElement('div', { className: 'status-text' }, error || 'Ready to evaluate.')
    ),
    React.createElement(
      'section',
      { className: 'panel dashboard-panel' },
      summary
        ? React.createElement(
            React.Fragment,
            null,
            React.createElement('div', { className: 'score-header' },
              React.createElement('div', { className: 'score-ring' },
                React.createElement('div', { className: 'score-ring-inner' },
                  React.createElement('strong', null, `${summary.total}/${summary.max}`),
                  React.createElement('span', null, 'overall')
                )
              ),
              React.createElement('div', { className: 'metrics' },
                React.createElement('div', { className: 'metric-card' },
                  React.createElement('span', null, 'Base score'),
                  React.createElement('strong', null, summary.base)
                ),
                React.createElement('div', { className: 'metric-card' },
                  React.createElement('span', null, 'Bonus'),
                  React.createElement('strong', null, `+${summary.bonus}`)
                ),
                React.createElement('div', { className: 'metric-card' },
                  React.createElement('span', null, 'Deductions'),
                  React.createElement('strong', null, `-${summary.deductions}`)
                )
              )
            ),
            React.createElement('div', { className: 'metrics-grid' },
              categoryEntries.map(([key, category]) =>
                React.createElement(CategoryMeter, {
                  key,
                  keyName: key,
                  title: key.replace(/_/g, ' '),
                  category,
                  width: Math.min(100, (category.score / category.max) * 100),
                })
              )
            ),
            React.createElement(
              'div',
              { className: 'insights-grid' },
              React.createElement(
                'div',
                { className: 'insight-card' },
                React.createElement('h3', null, 'Key strengths'),
                React.createElement('ul', null,
                  summary.strengths.map((item) => React.createElement('li', { key: item }, item))
                )
              ),
              React.createElement(
                'div',
                { className: 'insight-card' },
                React.createElement('h3', null, 'Areas for improvement'),
                React.createElement('ul', null,
                  summary.improvements.map((item) => React.createElement('li', { key: item }, item))
                )
              )
            ),
            React.createElement(
              'div',
              { className: 'raw-card' },
              React.createElement('h3', null, 'Raw API payload'),
              React.createElement('pre', null, prettyJson(result))
            )
          )
        : React.createElement(
            'div',
            { className: 'empty-state' },
            'No evaluation yet. Submit a path or upload a PDF to begin.'
          )
    )
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(App));
