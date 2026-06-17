(function () {
  let amapPromise = null;
  let activePicker = null;
  let activeMap = null;
  let activeMarker = null;
  let activePlaceSearch = null;
  let activeGeocoder = null;
  let activeSortCenter = null;

  function hasKey() {
    return !!(window.MAP_CONFIG && window.MAP_CONFIG.amapKey);
  }

  // 动态加载高德地图 JS API，并按需启用地点搜索、逆地理编码和浏览器定位插件。
  function loadAmap() {
    if (window.AMap) return Promise.resolve(window.AMap);
    if (amapPromise) return amapPromise;
    if (!hasKey()) return Promise.reject(new Error('未配置高德地图 Key'));

    amapPromise = new Promise((resolve, reject) => {
      if (window.MAP_CONFIG.securityJsCode) {
        window._AMapSecurityConfig = { securityJsCode: window.MAP_CONFIG.securityJsCode };
      }

      window.__onAmapLoaded = function () {
        if (!window.AMap) {
          reject(new Error('高德地图 JS API 加载失败'));
          return;
        }
        window.AMap.plugin(['AMap.PlaceSearch', 'AMap.Geocoder', 'AMap.Geolocation'], () => {
          resolve(window.AMap);
        });
      };

      const script = document.createElement('script');
      script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(window.MAP_CONFIG.amapKey)}&callback=__onAmapLoaded`;
      script.async = true;
      script.onerror = () => reject(new Error('无法加载高德地图脚本，请检查网络或 Key 配置'));
      document.head.appendChild(script);
    });
    return amapPromise;
  }

  // 复用一个全局地址选择弹窗，避免每个页面重复维护地图 DOM。
  function ensureModal() {
    let modal = document.getElementById('mapPickerModal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'mapPickerModal';
    modal.className = 'modal-overlay hidden';
    modal.innerHTML = `
      <div class="modal-content map-picker-modal">
        <div class="modal-header">
          <h3>选择地址</h3>
          <button class="modal-close" type="button" onclick="AddressPicker.close()">&times;</button>
        </div>
        <div class="map-picker-search">
          <input type="text" class="form-control" id="mapPickerKeyword" placeholder="搜索地点、写字楼、小区或商圈">
          <button class="btn btn-primary" type="button" id="mapPickerSearchBtn">搜索</button>
          <button class="btn btn-outline" type="button" id="mapPickerLocateBtn">当前定位</button>
        </div>
        <div class="map-picker-body">
          <div id="mapPickerMap"></div>
          <div id="mapPickerResults"></div>
        </div>
        <div class="map-picker-selected" id="mapPickerSelected">未选择地点</div>
        <button class="btn btn-primary btn-block mt-10" type="button" id="mapPickerConfirmBtn">使用此地址</button>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  // 对高德返回的 POI 文本做转义，避免把地点名称当作 HTML 注入页面。
  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, s => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[s]));
  }

  function showPickerMessage(message, type) {
    const list = document.getElementById('mapPickerResults');
    if (!list) return;
    list.innerHTML = `<div class="map-picker-empty ${type ? `map-picker-${type}` : ''}">${escapeHtml(message)}</div>`;
  }

  // 兼容高德 LngLat 对象和普通经纬度对象。
  function getLngLat(location) {
    if (!location) return null;
    const lng = typeof location.getLng === 'function' ? location.getLng() : location.lng;
    const lat = typeof location.getLat === 'function' ? location.getLat() : location.lat;
    if (lng === undefined || lat === undefined) return null;
    return { lng: Number(lng), lat: Number(lat) };
  }

  // 将选中的地址、经纬度和地点名称写回业务表单。
  function setInputs(picker, point) {
    const addressInput = document.getElementById(picker.addressInputId);
    const latInput = document.getElementById(picker.latInputId);
    const lngInput = document.getElementById(picker.lngInputId);
    const nameInput = document.getElementById(picker.nameInputId);
    if (addressInput) addressInput.value = point.address || point.name || '';
    if (latInput) latInput.value = point.latitude || '';
    if (lngInput) lngInput.value = point.longitude || '';
    if (nameInput) nameInput.value = point.name || '';
    if (addressInput) {
      addressInput.dispatchEvent(new CustomEvent('address-picked', { detail: point }));
      addressInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  // 选中地图点或搜索结果后，同步更新地图标记和弹窗底部的已选地址。
  function selectPoint(point) {
    const lnglat = getLngLat(point && point.location);
    if (!lnglat) return;

    activePicker.selected = {
      name: point.name || '',
      address: point.address || point.formattedAddress || point.name || '',
      latitude: lnglat.lat,
      longitude: lnglat.lng
    };

    activeMarker.setPosition([lnglat.lng, lnglat.lat]);
    activeMarker.show();
    activeMap.setZoomAndCenter(16, [lnglat.lng, lnglat.lat]);
    document.getElementById('mapPickerSelected').textContent =
      `${activePicker.selected.name || '已选地点'} ${activePicker.selected.address || ''}`;
  }

  // 前端只用于排序和展示的直线距离计算；订单最终配送费以后端计算为准。
  function distanceMeters(from, to) {
    const a = getLngLat(from);
    const b = getLngLat(to);
    if (!a || !b) return Number.POSITIVE_INFINITY;
    const rad = d => d * Math.PI / 180;
    const dLat = rad(b.lat - a.lat);
    const dLng = rad(b.lng - a.lng);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 6371008.8 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  // 搜索结果先按关键词相关性排序，同等相关性时再按参考点距离排序。
  function relevanceScore(poi, keyword) {
    const kw = String(keyword || '').trim().toLowerCase();
    if (!kw) return 0;
    const name = String(poi.name || '').toLowerCase();
    const address = String(poi.address || poi.district || '').toLowerCase();
    if (name === kw) return 0;
    if (name.startsWith(kw)) return 1;
    if (name.includes(kw)) return 2;
    if (address.includes(kw)) return 3;
    return 4;
  }

  // 高德返回距离时优先使用接口距离，否则用本地 Haversine 结果兜底。
  function poiDistance(poi) {
    if (!activeSortCenter) return Number.POSITIVE_INFINITY;
    const apiDistance = Number(poi.distance);
    if (Number.isFinite(apiDistance)) return apiDistance;
    return distanceMeters(activeSortCenter, poi.location);
  }

  function sortPois(pois, keyword) {
    return [...pois].sort((a, b) => {
      const relevanceDelta = relevanceScore(a, keyword) - relevanceScore(b, keyword);
      if (relevanceDelta !== 0) return relevanceDelta;
      return poiDistance(a) - poiDistance(b);
    });
  }

  function formatDistance(meters) {
    if (!Number.isFinite(meters)) return '';
    return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
  }

  function formatPoiMeta(poi) {
    const parts = [];
    if (poi.address || poi.district) parts.push(poi.address || poi.district);
    const distance = formatDistance(poiDistance(poi));
    if (distance) parts.push(distance);
    return parts.join(' · ');
  }

  // 渲染右侧地点列表，点击列表项即可作为当前地址。
  function renderResults(results, keyword = '') {
    const list = document.getElementById('mapPickerResults');
    if (!results.length) {
      showPickerMessage('没有找到地点，请换一个关键词或直接点击地图选点');
      return;
    }

    const sorted = sortPois(results, keyword);
    list.innerHTML = sorted.map((p, index) => `
      <button type="button" class="map-picker-result" data-index="${index}">
        <strong>${escapeHtml(p.name || '')}</strong>
        <span>${escapeHtml(formatPoiMeta(p))}</span>
      </button>
    `).join('');

    list.querySelectorAll('.map-picker-result').forEach(btn => {
      btn.addEventListener('click', () => selectPoint(sorted[Number(btn.dataset.index)]));
    });
  }

  // 按关键词搜索；已经有定位或地图选点时优先搜索附近，提高结果可用性。
  function searchKeyword(keyword) {
    if (!activePlaceSearch || !keyword) return;

    showPickerMessage('搜索中...');
    const searchFn = activeSortCenter
      ? cb => activePlaceSearch.searchNearBy(keyword, activeSortCenter, 30000, cb)
      : cb => activePlaceSearch.search(keyword, cb);

    searchFn((status, result) => {
      if (status !== 'complete') {
        const info = result && (result.info || result.message) ? `：${result.info || result.message}` : '';
        showPickerMessage(`搜索失败${info}。请确认高德 Key 是“Web端(JS API)”类型，并已配置安全密钥。`, 'error');
        return;
      }
      renderResults(result && result.poiList ? result.poiList.pois || [] : [], keyword);
    });
  }

  // 点击地图或定位成功后加载周边兴趣点，并按距离展示在右侧列表。
  function searchNearby(center, message = '正在加载附近地点...') {
    if (!activePlaceSearch || !center) return;
    activeSortCenter = center;
    showPickerMessage(message);

    activePlaceSearch.searchNearBy('', center, 1500, (status, result) => {
      if (status === 'complete' && result && result.poiList) {
        renderResults(result.poiList.pois || []);
        return;
      }

      activePlaceSearch.searchNearBy('大学 小区 写字楼 商场 餐饮', center, 1500, (fallbackStatus, fallbackResult) => {
        if (fallbackStatus === 'complete' && fallbackResult && fallbackResult.poiList) {
          renderResults(fallbackResult.poiList.pois || []);
          return;
        }
        showPickerMessage('附近地点加载失败。可以直接使用当前选点，或手动搜索地址。', 'error');
      });
    });
  }

  // 打开地址选择器。默认自动定位一次，定位失败时仍可手动搜索和点击地图选点。
  async function openPicker(options) {
    activePicker = { ...options, selected: null };
    const modal = ensureModal();
    modal.classList.remove('hidden');
    showPickerMessage('正在加载高德地图...');
    document.getElementById('mapPickerSelected').textContent = '未选择地点';

    try {
      const AMap = await loadAmap();
      const addressInput = document.getElementById(options.addressInputId);
      const initialKeyword = addressInput ? addressInput.value.trim() : '';
      const initialCenter = options.defaultCenter || [119.514, 32.207];

      if (activeMap) activeMap.destroy();
      activeSortCenter = null;
      activeMap = new AMap.Map('mapPickerMap', {
        zoom: 13,
        center: initialCenter,
        viewMode: '2D'
      });
      activeMarker = new AMap.Marker({ map: activeMap, visible: false });
      activeGeocoder = new AMap.Geocoder({ city: '全国' });
      activePlaceSearch = new AMap.PlaceSearch({
        pageSize: 10,
        pageIndex: 1,
        city: '全国',
        citylimit: false
      });

      setTimeout(() => activeMap.resize(), 100);
      showPickerMessage('输入关键词搜索地点，或直接点击地图选点');

      document.getElementById('mapPickerKeyword').value = initialKeyword;
      document.getElementById('mapPickerSearchBtn').onclick = () => {
        searchKeyword(document.getElementById('mapPickerKeyword').value.trim());
      };
      document.getElementById('mapPickerKeyword').oninput = debounce(() => {
        searchKeyword(document.getElementById('mapPickerKeyword').value.trim());
      }, 500);
      document.getElementById('mapPickerLocateBtn').onclick = () => locateCurrentPosition();
      document.getElementById('mapPickerConfirmBtn').onclick = confirmSelection;

      activeMap.on('click', event => {
        activeSortCenter = event.lnglat;
        activeGeocoder.getAddress(event.lnglat, (status, result) => {
          const address = status === 'complete' && result.regeocode ? result.regeocode.formattedAddress : '';
          selectPoint({ name: address || '地图选点', address, location: event.lnglat });
        });
        searchNearby(event.lnglat, '正在加载选点周围的地点...');
      });

      if (options.autoLocate === false) {
        if (initialKeyword) searchKeyword(initialKeyword);
      } else {
        locateCurrentPosition({
          showNearby: !initialKeyword,
          afterLocated: () => {
            if (initialKeyword) searchKeyword(initialKeyword);
          },
          afterFailed: () => {
            if (initialKeyword) searchKeyword(initialKeyword);
          }
        });
      }
    } catch (err) {
      showPickerMessage(`${err.message || '地图加载失败'}。你仍然可以关闭弹窗后手动输入地址。`, 'error');
      if (typeof showToast === 'function') {
        showToast('地图加载失败，请检查高德 Key 类型和安全密钥', 'warning');
      }
    }
  }

  // 获取当前位置后自动选中当前位置，并刷新附近兴趣点列表。
  function locateCurrentPosition(options = {}) {
    if (!window.AMap || !activeMap || !activeGeocoder) return;

    showPickerMessage('正在获取当前位置...');
    const geolocation = new window.AMap.Geolocation({
      enableHighAccuracy: true,
      timeout: 8000,
      showButton: false
    });

    geolocation.getCurrentPosition((status, result) => {
      if (status !== 'complete') {
        if (typeof options.afterFailed === 'function') options.afterFailed(result);
        showPickerMessage('无法获取当前位置，请允许浏览器定位权限，或手动搜索地址。', 'error');
        return;
      }

      const pos = result.position;
      activeSortCenter = pos;
      activeMap.setCenter(pos);
      selectPoint({ name: '当前位置', address: '当前位置', location: pos });
      if (options.showNearby !== false) searchNearby(pos);
      if (typeof options.afterLocated === 'function') options.afterLocated(pos, result);
      activeGeocoder.getAddress(pos, (geoStatus, geoResult) => {
        const address = geoStatus === 'complete' && geoResult.regeocode
          ? geoResult.regeocode.formattedAddress
          : '当前位置';
        selectPoint({ name: address, address, location: pos });
      });
    });
  }

  // 确认按钮只负责回填表单，是否提交由各业务页面自己处理。
  function confirmSelection() {
    if (!activePicker || !activePicker.selected) {
      if (typeof showToast === 'function') showToast('请先选择一个地点', 'warning');
      return;
    }
    setInputs(activePicker, activePicker.selected);
    AddressPicker.close();
  }

  // 输入搜索做防抖，减少对高德地点搜索接口的频繁调用。
  function debounce(fn, wait) {
    let timer = null;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  window.AddressPicker = {
    init(options) {
      const button = document.getElementById(options.buttonId);
      if (!button) return;
      if (!hasKey()) {
        button.classList.add('hidden');
        return;
      }
      button.addEventListener('click', () => openPicker(options));
    },
    close() {
      const modal = document.getElementById('mapPickerModal');
      if (modal) modal.classList.add('hidden');
    }
  };
})();
