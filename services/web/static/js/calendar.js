/**
 * Calendar rendering functions
 */

function renderCalendar(dates) {
    const container = document.getElementById('calendarContainer');
    
    if (!dates || dates.length === 0) {
        container.innerHTML = '<p class="no-results">Nėra surinkimo datų</p>';
        return;
    }
    
    // Group dates by month
    const datesByMonth = groupDatesByMonth(dates);
    
    // Render each month
    let html = '';
    for (const [yearMonth, monthDates] of Object.entries(datesByMonth)) {
        html += renderMonth(yearMonth, monthDates);
    }
    
    container.innerHTML = html;
}

function groupDatesByMonth(dates) {
    const grouped = {};
    
    dates.forEach(dateObj => {
        const dateStr = dateObj.date || dateObj;
        const date = new Date(dateStr);
        const year = date.getFullYear();
        const month = date.getMonth();
        const key = `${year}-${month}`;
        
        if (!grouped[key]) {
            grouped[key] = {
                year: year,
                month: month,
                dates: []
            };
        }
        
        grouped[key].dates.push(date);
    });
    
    return grouped;
}

function renderMonth(yearMonth, monthData) {
    const { year, month, dates } = monthData;
    const monthName = getMonthName(month);
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startDayOfWeek = firstDay.getDay();
    
    // Convert Sunday (0) to 6 for easier grid layout
    const startOffset = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;
    
    // Create set of pickup dates for quick lookup
    const pickupDates = new Set();
    dates.forEach(dateStr => {
        const date = new Date(dateStr);
        pickupDates.add(date.getDate());
    });
    
    // Day names in Lithuanian
    const dayNames = ['Pr', 'An', 'Tr', 'Kt', 'Pn', 'Št', 'Sk'];
    
    let html = `
        <div class="calendar-month">
            <div class="calendar-month-header">${monthName} ${year}</div>
            <div class="calendar-grid">
    `;
    
    // Day headers
    dayNames.forEach(day => {
        html += `<div class="calendar-day-header">${day}</div>`;
    });
    
    // Empty cells for days before month starts
    for (let i = 0; i < startOffset; i++) {
        html += '<div class="calendar-day empty"></div>';
    }
    
    // Days of the month
    for (let day = 1; day <= daysInMonth; day++) {
        const isPickup = pickupDates.has(day);
        const classes = ['calendar-day'];
        
        if (isPickup) {
            classes.push('pickup');
        }
        
        html += `<div class="${classes.join(' ')}" title="${isPickup ? 'Surinkimo diena' : ''}">${day}</div>`;
    }
    
    // Fill remaining cells to complete grid (7 columns)
    const totalCells = startOffset + daysInMonth;
    const remainingCells = 7 - (totalCells % 7);
    if (remainingCells < 7) {
        for (let i = 0; i < remainingCells; i++) {
            html += '<div class="calendar-day empty"></div>';
        }
    }
    
    html += `
            </div>
        </div>
    `;
    
    return html;
}

function getMonthName(monthIndex) {
    const months = [
        'Sausis', 'Vasaris', 'Kovas', 'Balandis', 'Gegužė', 'Birželis',
        'Liepa', 'Rugpjūtis', 'Rugsėjis', 'Spalis', 'Lapkritis', 'Gruodis'
    ];
    return months[monthIndex];
}
