// 源飯糰點餐系統 - 大螢幕點餐機前端

const API_KEY = 'yuan-secret-key';
let sessionId = 'session-' + Date.now();

// ============================================================================
// 應用狀態
// ============================================================================

const AppState = {
    INITIAL: 'initial',      // 初始狀態：等待語音
    ORDERING: 'ordering',    // 點餐中：顯示訂單列表
    CHECKOUT: 'checkout',    // 結帳流程
};

let currentState = AppState.INITIAL;
let orderData = {
    items: [],
    totalPrice: 0,
    dineType: null,
    paymentMethod: null,
};

// ============================================================================
// DOM 元素
// ============================================================================

const statusIndicator = document.getElementById('statusIndicator');

// 語音區域
const voiceArea = document.getElementById('voiceArea');
const voiceCircle = document.getElementById('voiceCircle');
const waveformCanvas = document.getElementById('waveformCanvas');
const voicePrompt = document.getElementById('voicePrompt');
const voiceStatus = document.getElementById('voiceStatus');

// 訂單區域
const orderArea = document.getElementById('orderArea');
const orderItems = document.getElementById('orderItems');
const orderTotal = document.getElementById('orderTotal');
const voiceCircleSmall = document.getElementById('voiceCircleSmall');
const waveformCanvasSmall = document.getElementById('waveformCanvasSmall');
const voiceStatusSmall = document.getElementById('voiceStatusSmall');
const checkoutBtn = document.getElementById('checkoutBtn');
const clearOrderBtn = document.getElementById('clearOrderBtn');

// 結帳流程
const checkoutFlow = document.getElementById('checkoutFlow');
const stepDineType = document.getElementById('stepDineType');
const stepPayment = document.getElementById('stepPayment');
const stepConfirm = document.getElementById('stepConfirm');
const stepComplete = document.getElementById('stepComplete');
const checkoutBackBtn = document.getElementById('checkoutBackBtn');
const confirmOrderBtn = document.getElementById('confirmOrderBtn');
const newOrderBtn = document.getElementById('newOrderBtn');

// ============================================================================
// 語音相關變數
// ============================================================================

let audioContext = null;
let analyser = null;
let microphone = null;
let mediaRecorder = null;
let audioChunks = [];
let currentStream = null;

// VAD 設定
const VAD_THRESHOLD = 15;           // 音量閾值
const SILENCE_DURATION = 1500;      // 靜音持續時間（毫秒）
let isListening = false;
let isRecording = false;
let silenceStart = null;
let vadAnimationId = null;

// ============================================================================
// 初始化
// ============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('初始化點餐系統...');
    await loadStoreConfig();
    await checkConnection();
    setupEventListeners();
    startVoiceActivation();
});

// ============================================================================
// 載入店家設定
// ============================================================================

async function loadStoreConfig() {
    try {
        const response = await fetch('/api/store-config');
        const config = await response.json();

        // 更新店名
        const storeNameEl = document.getElementById('storeName');
        if (storeNameEl && config.store) {
            storeNameEl.textContent = config.store.name;
            document.title = `${config.store.name} ${config.store.subtitle || ''}`;
        }

        console.log('店家設定載入完成:', config.store.name);
    } catch (error) {
        console.error('載入店家設定失敗:', error);
        document.getElementById('storeName').textContent = '點餐系統';
    }
}

// ============================================================================
// 連線檢查
// ============================================================================

async function checkConnection() {
    const dot = statusIndicator.querySelector('.status-dot');
    const text = statusIndicator.querySelector('.status-text');

    try {
        const response = await fetch('/healthz');
        if (response.ok) {
            dot.className = 'status-dot online';
            text.textContent = '已連線';
        } else {
            throw new Error('Server error');
        }
    } catch (error) {
        dot.className = 'status-dot offline';
        text.textContent = '離線';
    }
}

// ============================================================================
// 菜單（PDF 顯示，無需動態載入）
// ============================================================================

// PDF 菜單已在 HTML 中直接嵌入，無需額外載入

// ============================================================================
// 事件監聽設定
// ============================================================================

function setupEventListeners() {
    // 結帳按鈕
    checkoutBtn.addEventListener('click', startCheckout);

    // 清空訂單
    clearOrderBtn.addEventListener('click', clearOrder);

    // 結帳流程選項
    stepDineType.querySelectorAll('.checkout-option').forEach(btn => {
        btn.addEventListener('click', () => selectDineType(btn.dataset.value));
    });

    stepPayment.querySelectorAll('.checkout-option').forEach(btn => {
        btn.addEventListener('click', () => selectPaymentMethod(btn.dataset.value));
    });

    // 確認訂單
    confirmOrderBtn.addEventListener('click', confirmOrder);

    // 返回按鈕
    checkoutBackBtn.addEventListener('click', goBackInCheckout);

    // 新訂單
    newOrderBtn.addEventListener('click', startNewOrder);
}

// ============================================================================
// 語音喚醒系統
// ============================================================================

async function startVoiceActivation() {
    try {
        currentStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                sampleRate: 16000
            }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.8;

        microphone = audioContext.createMediaStreamSource(currentStream);
        microphone.connect(analyser);

        isListening = true;
        voiceStatus.textContent = '語音喚醒已啟用';
        voiceStatus.classList.add('listening');

        // 開始監聽音量
        startVADLoop();

    } catch (error) {
        console.error('無法存取麥克風:', error);
        voiceStatus.textContent = '無法存取麥克風';
    }
}

function startVADLoop() {
    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    function loop() {
        if (!isListening) return;

        analyser.getByteFrequencyData(dataArray);

        // 計算平均音量
        const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

        // 繪製波形
        drawWaveform(average);

        // VAD 邏輯
        if (average > VAD_THRESHOLD) {
            // 偵測到聲音
            silenceStart = null;

            if (!isRecording) {
                startRecording();
            }

            // 更新視覺狀態
            updateVoiceCircleState('recording');

        } else if (isRecording) {
            // 正在錄音但沒有聲音
            if (!silenceStart) {
                silenceStart = Date.now();
            } else if (Date.now() - silenceStart > SILENCE_DURATION) {
                // 靜音超過閾值，停止錄音
                stopRecording();
                silenceStart = null;
                updateVoiceCircleState('active');
            }
        }

        vadAnimationId = requestAnimationFrame(loop);
    }

    loop();
}

function updateVoiceCircleState(state) {
    const circles = [voiceCircle, voiceCircleSmall];
    const statuses = [voiceStatus, voiceStatusSmall];

    circles.forEach(circle => {
        if (!circle) return;
        circle.classList.remove('active', 'recording');
        if (state) circle.classList.add(state);
    });

    if (state === 'recording') {
        if (voiceStatus) {
            voiceStatus.textContent = '錄音中...';
            voiceStatus.classList.add('recording');
            voiceStatus.classList.remove('listening');
        }
        if (voiceStatusSmall) {
            voiceStatusSmall.textContent = '錄音中...';
        }
    } else if (state === 'active') {
        if (voiceStatus) {
            voiceStatus.textContent = '語音喚醒已啟用';
            voiceStatus.classList.remove('recording');
            voiceStatus.classList.add('listening');
        }
        if (voiceStatusSmall) {
            voiceStatusSmall.textContent = '繼續說話點餐';
        }
    }
}

// ============================================================================
// 波形繪製
// ============================================================================

function drawWaveform(volume) {
    // 繪製大圓形波形
    if (waveformCanvas) {
        drawCircularWaveform(waveformCanvas, volume, 280);
    }

    // 繪製小圓形波形
    if (waveformCanvasSmall && currentState === AppState.ORDERING) {
        drawCircularWaveform(waveformCanvasSmall, volume, 80);
    }
}

function drawCircularWaveform(canvas, volume, size) {
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // 設置 canvas 大小
    if (canvas.width !== size * dpr) {
        canvas.width = size * dpr;
        canvas.height = size * dpr;
        ctx.scale(dpr, dpr);
    }

    const centerX = size / 2;
    const centerY = size / 2;
    const baseRadius = size * 0.3;
    const maxAmplitude = size * 0.15;

    ctx.clearRect(0, 0, size, size);

    // 繪製多層波形
    const layers = 3;
    const normalizedVolume = Math.min(volume / 50, 1);

    for (let layer = 0; layer < layers; layer++) {
        const layerOpacity = 0.3 - layer * 0.08;
        const layerRadius = baseRadius + layer * 8;
        const amplitude = normalizedVolume * maxAmplitude * (1 - layer * 0.2);

        ctx.beginPath();

        const segments = 60;
        const time = Date.now() / 1000;

        for (let i = 0; i <= segments; i++) {
            const angle = (i / segments) * Math.PI * 2;
            const noise = Math.sin(angle * 6 + time * 3 + layer) * 0.5 + 0.5;
            const r = layerRadius + amplitude * noise;

            const x = centerX + Math.cos(angle) * r;
            const y = centerY + Math.sin(angle) * r;

            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }

        ctx.closePath();

        // 漸變顏色
        const gradient = ctx.createRadialGradient(
            centerX, centerY, 0,
            centerX, centerY, layerRadius + amplitude
        );

        if (isRecording) {
            // 錄音中：柔和紅色（淺色主題加深）
            gradient.addColorStop(0, `rgba(196, 92, 92, ${layerOpacity + 0.2})`);
            gradient.addColorStop(1, `rgba(196, 92, 92, ${layerOpacity})`);
        } else {
            // 待機：低飽和藍綠 #729DAD（淺色主題加深）
            gradient.addColorStop(0, `rgba(90, 132, 148, ${layerOpacity + 0.2})`);
            gradient.addColorStop(1, `rgba(114, 157, 173, ${layerOpacity})`);
        }

        ctx.fillStyle = gradient;
        ctx.fill();
    }
}

// ============================================================================
// 錄音功能
// ============================================================================

function startRecording() {
    if (isRecording) return;

    console.log('開始錄音...');
    isRecording = true;

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

    mediaRecorder = new MediaRecorder(currentStream, { mimeType });
    audioChunks = [];

    mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
            audioChunks.push(e.data);
        }
    };

    mediaRecorder.onstop = async () => {
        console.log('錄音停止，處理音訊...');
        const audioBlob = new Blob(audioChunks, { type: mimeType });

        if (audioBlob.size > 1000) {
            await sendVoiceMessage(audioBlob);
        } else {
            console.log('錄音太短，忽略');
        }

        isRecording = false;
        updateVoiceCircleState('active');
    };

    mediaRecorder.start(200);
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        console.log('停止錄音...');
        mediaRecorder.requestData();
        mediaRecorder.stop();
    }
}

// ============================================================================
// 語音訊息處理
// ============================================================================

async function sendVoiceMessage(audioBlob) {
    const formData = new FormData();
    formData.append('session_id', sessionId);
    formData.append('audio_file', audioBlob, 'recording.webm');

    try {
        const response = await fetch('/dialogue/voice', {
            method: 'POST',
            headers: { 'X-API-Key': API_KEY },
            body: formData
        });

        const data = await response.json();

        if (data.status === 'ok') {
            console.log('使用者說:', data.user_text);
            console.log('系統回應:', data.response);

            // 檢查是否需要切換到點餐狀態
            if (currentState === AppState.INITIAL) {
                switchToOrderingState();
            }

            // 更新購物車
            await refreshCart();

            // 檢查是否要結帳
            if (data.user_text && (
                data.user_text.includes('結帳') ||
                data.user_text.includes('買單') ||
                data.user_text.includes('付錢')
            )) {
                startCheckout();
            }

            // 播放 TTS
            if (data.audio_url) {
                playTTSAudio(data.audio_url);
            }
        }
    } catch (error) {
        console.error('語音處理失敗:', error);
    }
}


// ============================================================================
// 狀態切換
// ============================================================================

function switchToOrderingState() {
    console.log('切換到點餐狀態');
    currentState = AppState.ORDERING;

    voiceArea.classList.add('hidden');
    orderArea.classList.remove('hidden');
    checkoutFlow.classList.add('hidden');
}

function switchToInitialState() {
    console.log('切換到初始狀態');
    currentState = AppState.INITIAL;

    voiceArea.classList.remove('hidden');
    orderArea.classList.add('hidden');
    checkoutFlow.classList.add('hidden');
}

function switchToCheckoutState() {
    console.log('切換到結帳狀態');
    currentState = AppState.CHECKOUT;

    voiceArea.classList.add('hidden');
    orderArea.classList.add('hidden');
    checkoutFlow.classList.remove('hidden');
}

// ============================================================================
// 購物車更新
// ============================================================================

async function refreshCart() {
    try {
        const response = await fetch('/cart/summary?session_id=' + sessionId, {
            headers: { 'X-API-Key': API_KEY }
        });

        const data = await response.json();

        if (data.ok && data.items && data.items.length > 0) {
            orderData.items = data.items;
            orderData.totalPrice = data.total_price;

            orderItems.innerHTML = data.items.map((item, index) => `
                <div class="order-item">
                    <div class="order-item-info">
                        <span class="order-item-index">${index + 1}</span>
                        <span class="order-item-name">${escapeHtml(item.name)}</span>
                        <span class="order-item-qty">x${item.quantity}</span>
                    </div>
                    <span class="order-item-price">${item.price || ''}</span>
                </div>
            `).join('');

            orderTotal.textContent = '$' + data.total_price;
            checkoutBtn.disabled = false;

        } else {
            orderData.items = [];
            orderData.totalPrice = 0;

            orderItems.innerHTML = '<div class="order-empty">尚未點餐</div>';
            orderTotal.textContent = '$0';
            checkoutBtn.disabled = true;
        }
    } catch (error) {
        console.log('更新購物車失敗:', error);
    }
}

// ============================================================================
// 清空訂單
// ============================================================================

async function clearOrder() {
    try {
        // 發送清空購物車的請求
        await fetch('/dialogue/text', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
            },
            body: JSON.stringify({
                session_id: sessionId,
                text: '清空購物車'
            })
        });

        orderData.items = [];
        orderData.totalPrice = 0;

        orderItems.innerHTML = '<div class="order-empty">尚未點餐</div>';
        orderTotal.textContent = '$0';
        checkoutBtn.disabled = true;

    } catch (error) {
        console.error('清空訂單失敗:', error);
    }
}

// ============================================================================
// 結帳流程
// ============================================================================

let checkoutStep = 1;

function startCheckout() {
    if (orderData.items.length === 0) return;

    checkoutStep = 1;
    orderData.dineType = null;
    orderData.paymentMethod = null;

    switchToCheckoutState();
    showCheckoutStep(1);
}

function showCheckoutStep(step) {
    checkoutStep = step;

    // 隱藏所有步驟
    [stepDineType, stepPayment, stepConfirm, stepComplete].forEach(s => {
        s.classList.add('hidden');
    });

    // 顯示當前步驟
    switch (step) {
        case 1:
            stepDineType.classList.remove('hidden');
            checkoutBackBtn.classList.add('hidden');
            break;
        case 2:
            stepPayment.classList.remove('hidden');
            checkoutBackBtn.classList.remove('hidden');
            break;
        case 3:
            stepConfirm.classList.remove('hidden');
            checkoutBackBtn.classList.remove('hidden');
            renderConfirmPage();
            break;
        case 4:
            stepComplete.classList.remove('hidden');
            checkoutBackBtn.classList.add('hidden');
            break;
    }
}

function selectDineType(value) {
    orderData.dineType = value;
    showCheckoutStep(2);
}

function selectPaymentMethod(value) {
    orderData.paymentMethod = value;
    showCheckoutStep(3);
}

function renderConfirmPage() {
    // 訂單明細
    const summaryEl = document.getElementById('confirmSummary');
    summaryEl.innerHTML = orderData.items.map(item => `
        <div class="confirm-item">
            <span>${escapeHtml(item.name)} x${item.quantity}</span>
            <span>${item.price || ''}</span>
        </div>
    `).join('');

    // 用餐方式
    document.getElementById('confirmDineType').textContent =
        orderData.dineType === 'dine-in' ? '內用' : '外帶';

    // 付款方式
    document.getElementById('confirmPayment').textContent =
        orderData.paymentMethod === 'cash' ? '現金' : '行動支付';

    // 總計
    document.getElementById('confirmTotal').textContent = '$' + orderData.totalPrice;
}

function goBackInCheckout() {
    if (checkoutStep > 1) {
        showCheckoutStep(checkoutStep - 1);
    }
}

async function confirmOrder() {
    try {
        // 發送確認訂單請求
        const response = await fetch('/dialogue/text', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
            },
            body: JSON.stringify({
                session_id: sessionId,
                text: '確認結帳'
            })
        });

        const data = await response.json();
        console.log('確認訂單結果:', data);

        // 生成取餐號碼
        const orderNumber = Math.floor(Math.random() * 100) + 1;
        document.getElementById('orderNumber').textContent = orderNumber.toString().padStart(2, '0');

        showCheckoutStep(4);

    } catch (error) {
        console.error('確認訂單失敗:', error);
    }
}

function startNewOrder() {
    // 重新生成 session ID
    sessionId = 'session-' + Date.now();

    // 重置訂單數據
    orderData = {
        items: [],
        totalPrice: 0,
        dineType: null,
        paymentMethod: null,
    };

    // 切換回初始狀態
    switchToInitialState();
}

// ============================================================================
// TTS 播放
// ============================================================================

function playTTSAudio(audioUrl) {
    console.log('播放 TTS 音訊:', audioUrl);

    // 暫停 VAD
    isListening = false;

    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    const audioSrc = audioUrl.includes('\\') || audioUrl.includes(':/')
        ? '/tts/play?path=' + encodeURIComponent(audioUrl)
        : audioUrl;

    fetch(audioSrc, { headers: { 'X-API-Key': API_KEY } })
        .then(response => response.arrayBuffer())
        .then(arrayBuffer => audioContext.decodeAudioData(arrayBuffer))
        .then(audioBuffer => {
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);

            source.onended = () => {
                console.log('TTS 播放完畢');
                isListening = true;
                startVADLoop();
            };

            source.start(0);
        })
        .catch(e => {
            console.error('播放失敗:', e);
            isListening = true;
            startVADLoop();
        });
}

// ============================================================================
// 工具函數
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

