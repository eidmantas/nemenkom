/**
 * Calendar rendering functions
 */

function renderCalendar(dates) {
    const container = document.getElementById('calendarContainer');
    
    if (!dates || dates.length === 0) {
        container.innerHTML = '<p class="no-results">Nėra surinkimo datų</p>';
        return;
    }
    
    const visibleMonthKeys = getVisibleVilniusMonthKeys();
    const visibleMonthSet = new Set(visibleMonthKeys);
    const visibleDates = dates.filter(dateObj => {
        const dateStr = dateObj.date || dateObj;
        return visibleMonthSet.has(getDateMonthKey(dateStr));
    });

    if (visibleDates.length === 0) {
        container.innerHTML = '<p class="no-results">Nėra matomo laikotarpio surinkimo datų</p>';
        return;
    }

    // Group dates by month
    const datesByMonth = groupDatesByMonth(visibleDates);
    
    // Render each month
    let html = '';
    visibleMonthKeys.forEach(yearMonth => {
        html += renderMonth(yearMonth, datesByMonth[yearMonth] || createEmptyMonthData(yearMonth));
    });
    
    container.innerHTML = html;
}

function groupDatesByMonth(dates) {
    const grouped = {};
    
    dates.forEach(dateObj => {
        const dateStr = dateObj.date || dateObj;
        const wasteType = (dateObj && dateObj.waste_type) ? dateObj.waste_type : null;
        const { year, monthIndex, day } = parseIsoDateParts(dateStr);
        const key = getDateMonthKey(dateStr);
        
        if (!grouped[key]) {
            grouped[key] = {
                year: year,
                month: monthIndex,
                pickupTypesByDay: {}
            };
        }

        if (!grouped[key].pickupTypesByDay[day]) {
            grouped[key].pickupTypesByDay[day] = new Set();
        }
        if (wasteType) {
            grouped[key].pickupTypesByDay[day].add(wasteType);
        } else {
            // Backward compatibility: old API may return date strings only.
            grouped[key].pickupTypesByDay[day].add('pickup');
        }
    });
    
    return grouped;
}

function getDateMonthKey(dateStr) {
    return String(dateStr).slice(0, 7);
}

function createEmptyMonthData(yearMonth) {
    const [year, month] = yearMonth.split('-').map(Number);
    return {
        year: year,
        month: month - 1,
        pickupTypesByDay: {}
    };
}

function parseIsoDateParts(dateStr) {
    const [year, month, day] = String(dateStr).slice(0, 10).split('-').map(Number);
    return {
        year: year,
        monthIndex: month - 1,
        day: day
    };
}

function getCurrentVilniusDateParts() {
    const formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Vilnius',
        year: 'numeric',
        month: '2-digit',
    });
    const parts = formatter.formatToParts(new Date());
    return {
        year: Number(parts.find(part => part.type === 'year')?.value),
        month: Number(parts.find(part => part.type === 'month')?.value),
    };
}

function getVisibleVilniusMonthKeys() {
    const current = getCurrentVilniusDateParts();
    let startYear = current.year;
    let startMonth = current.month - 1;
    if (startMonth === 0) {
        startYear -= 1;
        startMonth = 12;
    }

    const months = [];
    if (startYear < current.year) {
        months.push(`${startYear}-${String(startMonth).padStart(2, '0')}`);
        startMonth = 1;
        startYear = current.year;
    }

    for (let month = startMonth; month <= 12; month++) {
        months.push(`${current.year}-${String(month).padStart(2, '0')}`);
    }
    return months;
}

function renderMonth(yearMonth, monthData) {
    const { year, month, pickupTypesByDay } = monthData;
    const monthName = getMonthName(month);
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startDayOfWeek = firstDay.getDay();
    
    // Convert Sunday (0) to 6 for easier grid layout
    const startOffset = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;
    
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
        const typeSet = pickupTypesByDay[day];
        const isPickup = !!typeSet;
        const classes = ['calendar-day'];
        
        if (isPickup) {
            classes.push('pickup');
        }

        let markersHtml = '';
        if (isPickup) {
            const types = Array.from(typeSet);
            markersHtml = `<div class="calendar-markers">${
                types
                    .filter(t => t !== 'pickup')
                    .map(t => `<span class="calendar-marker calendar-marker-${t}" title="${t}"></span>`)
                    .join('')
            }</div>`;
        }

        const title = isPickup ? 'Surinkimo diena' : '';
        html += `
            <div class="${classes.join(' ')}" title="${title}">
                <div class="calendar-day-num">${day}</div>
                ${markersHtml}
            </div>
        `;
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

function renderLegend(wasteTypes) {
    const legend = document.getElementById('calendarLegend');
    if (!legend) return;
    if (!wasteTypes || wasteTypes.length === 0) {
        legend.innerHTML = '';
        return;
    }

    const labelMap = {
        bendros: 'Bendros',
        plastikas: 'Plastikas',
        stiklas: 'Stiklas',
    };

    const items = wasteTypes.map(wt => {
        const label = labelMap[wt] || wt;
        return `
            <div class="calendar-legend-item">
                <span class="calendar-marker calendar-marker-${wt}"></span>
                <span class="calendar-legend-label">${label}</span>
            </div>
        `;
    }).join('');

    legend.innerHTML = `<div class="calendar-legend-inner">${items}</div>`;
}
