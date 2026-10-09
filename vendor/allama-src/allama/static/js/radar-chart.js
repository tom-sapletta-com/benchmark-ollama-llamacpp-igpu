/**
 * Allama Benchmark - Radar Chart Generator
 * Wspólny komponent do generowania wykresów radarowych dla benchmarków
 */

class AllamaRadarChart {
    /**
     * Inicjalizuje wykres radarowy
     * @param {string} canvasId - ID elementu canvas do rysowania wykresu
     * @param {Array} labels - Etykiety osi wykresu
     * @param {Object} datasets - Dane dla każdego modelu
     * @param {Object} options - Opcje konfiguracyjne wykresu
     */
    constructor(canvasId, labels, datasets, options = {}) {
        this.canvasId = canvasId;
        this.labels = labels;
        this.datasets = datasets;
        this.options = options;
        this.chart = null;
        
        // Domyślne kolory dla modeli
        this.colors = [
            ['rgba(255, 99, 132, 0.2)', 'rgba(255, 99, 132, 1)'],
            ['rgba(54, 162, 235, 0.2)', 'rgba(54, 162, 235, 1)'],
            ['rgba(255, 206, 86, 0.2)', 'rgba(255, 206, 86, 1)'],
            ['rgba(75, 192, 192, 0.2)', 'rgba(75, 192, 192, 1)'],
            ['rgba(153, 102, 255, 0.2)', 'rgba(153, 102, 255, 1)'],
            ['rgba(255, 159, 64, 0.2)', 'rgba(255, 159, 64, 1)']
        ];
    }
    
    /**
     * Przygotowuje dane do wykresu
     * @returns {Object} - Dane do wykresu Chart.js
     */
    prepareChartData() {
        const formattedDatasets = [];
        let i = 0;
        
        for (const [modelName, data] of Object.entries(this.datasets)) {
            const colorIndex = i % this.colors.length;
            const bgColor = this.colors[colorIndex][0];
            const borderColor = this.colors[colorIndex][1];
            
            formattedDatasets.push({
                label: modelName,
                data: data,
                backgroundColor: bgColor,
                borderColor: borderColor,
                borderWidth: 1
            });
            
            i++;
        }
        
        return {
            labels: this.labels,
            datasets: formattedDatasets
        };
    }
    
    /**
     * Przygotowuje opcje wykresu
     * @returns {Object} - Opcje konfiguracyjne dla Chart.js
     */
    prepareChartOptions() {
        const defaultOptions = {
            scales: {
                r: {
                    min: 0,
                    max: 100,
                    ticks: {
                        display: false
                    }
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        boxWidth: 10,
                        font: {
                            size: 10
                        }
                    }
                }
            },
            maintainAspectRatio: false
        };
        
        return {...defaultOptions, ...this.options};
    }
    
    /**
     * Renderuje wykres radarowy
     */
    render() {
        const ctx = document.getElementById(this.canvasId).getContext('2d');
        const chartData = this.prepareChartData();
        const chartOptions = this.prepareChartOptions();
        
        this.chart = new Chart(ctx, {
            type: 'radar',
            data: chartData,
            options: chartOptions
        });
        
        return this.chart;
    }
    
    /**
     * Aktualizuje dane wykresu
     * @param {Object} newDatasets - Nowe dane dla modeli
     */
    updateData(newDatasets) {
        this.datasets = newDatasets;
        if (this.chart) {
            this.chart.data = this.prepareChartData();
            this.chart.update();
        }
    }
}

/**
 * Funkcja pomocnicza do obliczania danych dla wykresu radarowego na podstawie wyników benchmarku
 * @param {Object} results - Wyniki benchmarku
 * @returns {Object} - Dane do wykresu radarowego
 */
function calculateRadarChartData(results) {
    const chartLabels = ['Sukces', 'Szybkość', 'Składnia', 'Wykonanie', 'Słowa kluczowe', 'Jakość'];
    const chartData = {};
    
    if (!results || !results.results || !Array.isArray(results.results)) {
        return { chartLabels, chartData };
    }
    
    const modelsData = {};
    
    // Grupuj wyniki według modeli
    for (const result of results.results) {
        const modelName = result.model_name || 'unknown';
        if (!modelsData[modelName]) {
            modelsData[modelName] = {
                success: 0,
                response_time: 0,
                syntax_correct: 0,
                execution_success: 0,
                keywords_present: 0,
                code_quality: 0,
                count: 0
            };
        }
        
        modelsData[modelName].count++;
        
        // Sukces
        if (result.success) {
            modelsData[modelName].success++;
        }
        
        // Czas odpowiedzi (niższy = lepszy)
        const responseTime = result.response_time || 0;
        modelsData[modelName].response_time += responseTime;
        
        // Poprawność składni
        if (result.evaluation && result.evaluation.syntax_correct) {
            modelsData[modelName].syntax_correct++;
        }
        
        // Powodzenie wykonania
        if (result.evaluation && result.evaluation.execution_success) {
            modelsData[modelName].execution_success++;
        }
        
        // Obecność słów kluczowych
        if (result.evaluation && result.evaluation.keywords_present) {
            modelsData[modelName].keywords_present++;
        }
        
        // Jakość kodu
        if (result.evaluation && result.evaluation.code_quality) {
            modelsData[modelName].code_quality += result.evaluation.code_quality;
        }
    }
    
    // Oblicz średnie wartości dla każdego modelu
    for (const [modelName, modelData] of Object.entries(modelsData)) {
        const count = Math.max(1, modelData.count);
        const successRate = (modelData.success / count) * 100;
        
        // Normalizuj czas odpowiedzi (odwrotnie - niższy czas = wyższy wynik)
        const avgTime = modelData.response_time / count;
        const maxTime = 10; // Zakładamy, że 10 sekund to maksymalny akceptowalny czas
        const timeScore = Math.max(0, 100 - ((avgTime / maxTime) * 100));
        
        const syntaxScore = (modelData.syntax_correct / count) * 100;
        const executionScore = (modelData.execution_success / count) * 100;
        const keywordsScore = (modelData.keywords_present / count) * 100;
        const qualityScore = (modelData.code_quality / count) * 20; // Zakładamy skalę 0-5, mnożymy przez 20
        
        chartData[modelName] = [
            successRate,
            timeScore,
            syntaxScore,
            executionScore,
            keywordsScore,
            qualityScore
        ];
    }
    
    return { chartLabels, chartData };
}
