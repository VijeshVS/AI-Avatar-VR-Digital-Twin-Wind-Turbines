using System;
using UnityEngine;
using Vrar.Health;

namespace Vrar.Avatar
{
    /// <summary>
    /// One turbine component rendered as an avatar: it carries a material, a
    /// vibration signal from telemetry and an optional audio source, and it
    /// expresses its health perceptually instead of printing a number.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class ComponentAvatar : MonoBehaviour
    {
        [Header("Identity")]
        [SerializeField] private string _componentId = "gearbox";
        [SerializeField] private string _label = "Gearbox";

        [Header("Expression")]
        [SerializeField, Range(0f, 1f)] private float _health = 1f;
        [SerializeField, Min(0f)] private float _vibrationAmplitude;
        [SerializeField, Min(0f)] private float _vibrationHz = 12f;
        [SerializeField, Min(0f)] private float _emissionScale = 2.5f;
        [SerializeField] private Renderer[] _renderers = Array.Empty<Renderer>();

        private MaterialPropertyBlock _propertyBlock;
        private Vector3 _restPosition;
        private float _noiseSeed;
        private AudioSource _alarmSource;
        private float _alarmPhase;

        public string ComponentId => _componentId;
        public string Label => _label;
        public float Health => _health;
        public float VibrationAmplitude => _vibrationAmplitude;
        public Color CurrentColor => HealthPalette.ColorFor(_health);

        public void Configure(string componentId, string label, Renderer[] renderers)
        {
            _componentId = componentId;
            _label = label;
            if (renderers != null && renderers.Length > 0)
            {
                _renderers = renderers;
            }
        }

        public void AttachAlarm(AudioSource source)
        {
            _alarmSource = source;
        }

        /// <summary>Apply a telemetry component payload. Safe to call every frame.</summary>
        public void Apply(Vrar.Telemetry.ComponentPayload component)
        {
            if (component == null)
            {
                return;
            }

            _health = Mathf.Clamp01(component.health);
            _label = string.IsNullOrEmpty(component.label) ? _label : component.label;
        }

        /// <summary>Apply the vibration amplitude carried by the plant signals (mm/s).</summary>
        public void SetVibration(float millimetresPerSecond)
        {
            _vibrationAmplitude = Mathf.Max(0f, millimetresPerSecond);
        }

        private void Awake()
        {
            _propertyBlock = new MaterialPropertyBlock();
            _restPosition = transform.localPosition;
            _noiseSeed = UnityEngine.Random.Range(0f, 100f);
        }

        private void Update()
        {
            float distress = HealthPalette.Distress(_health);
            ApplyColor(distress);
            ApplyTremor(distress);
            UpdateAlarm(distress);
        }

        private void ApplyColor(float distress)
        {
            Color color = HealthPalette.ColorFor(_health);
            // Failing parts glow harder and breathe faster: the pulse rate rises
            // with distress so degradation is legible from across the room.
            float pulse = 0.75f + 0.25f * Mathf.Sin(Time.time * Mathf.Lerp(1.5f, 6f, distress) + _noiseSeed);
            float emission = Mathf.Lerp(0.15f, _emissionScale, distress * distress) * pulse;

            foreach (Renderer target in _renderers)
            {
                if (target == null)
                {
                    continue;
                }

                target.GetPropertyBlock(_propertyBlock);
                _propertyBlock.SetColor("_BaseColor", color);
                _propertyBlock.SetColor("_Color", color);
                _propertyBlock.SetColor("_EmissionColor", color * emission);
                target.SetPropertyBlock(_propertyBlock);
            }
        }

        private void ApplyTremor(float distress)
        {
            if (distress <= 0.01f)
            {
                transform.localPosition = _restPosition;
                return;
            }

            float amplitude = _vibrationAmplitude * 0.0015f * (0.3f + distress);
            float time = Time.time * _vibrationHz;
            Vector3 offset = new Vector3(
                (Mathf.PerlinNoise(_noiseSeed, time) - 0.5f) * 2f,
                (Mathf.PerlinNoise(time, _noiseSeed) - 0.5f) * 2f,
                (Mathf.PerlinNoise(time + 31.4f, _noiseSeed + 7.1f) - 0.5f) * 2f);
            transform.localPosition = _restPosition + offset * amplitude;
        }

        private void UpdateAlarm(float distress)
        {
            if (_alarmSource == null)
            {
                return;
            }

            if (distress < 0.55f)
            {
                _alarmSource.Stop();
                _alarmSource.volume = 0f;
                return;
            }

            float rate = Mathf.Lerp(0.6f, 3.2f, Mathf.InverseLerp(0.55f, 1f, distress));
            _alarmPhase += Time.deltaTime * rate;
            float beep = Mathf.PingPong(_alarmPhase, 1f);
            _alarmSource.volume = Mathf.Lerp(0.05f, 0.35f, Mathf.InverseLerp(0.55f, 1f, distress))
                                  * (1f - Mathf.Abs(beep - 0.5f) * 2f);

            if (!_alarmSource.isPlaying)
            {
                _alarmSource.Play();
            }
        }

#if UNITY_EDITOR
        private void OnDrawGizmosSelected()
        {
            Gizmos.color = HealthPalette.ColorFor(_health);
            Gizmos.DrawWireSphere(transform.position, 1.5f);
        }
#endif
    }
}