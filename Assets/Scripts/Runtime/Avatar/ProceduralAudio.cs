using UnityEngine;

namespace Vrar.Avatar
{
    /// <summary>
    /// Synthesises the drivetrain hum and the alarm tone at runtime.
    ///
    /// Generating clips in code keeps the project free of paid or licensed audio
    /// assets, which the pilot requires, and lets pitch track rotor speed
    /// continuously instead of crossfading between loops.
    /// </summary>
    public sealed class ProceduralAudio : MonoBehaviour
    {
        private const int SampleRate = 44100;

        [SerializeField, Range(0f, 1f)] private float _masterVolume = 0.5f;

        private AudioSource _humSource;
        private AudioClip _humClip;
        private AudioSource _alarmSource;
        private AudioClip _alarmClip;
        private float _humPhase;

        public AudioSource HumSource => _humSource;
        public AudioSource AlarmSource => _alarmSource;

        private void Awake()
        {
            BuildSources();
        }

        private void BuildSources()
        {
            _humClip = BuildHumClip();
            _humSource = gameObject.AddComponent<AudioSource>();
            _humSource.clip = _humClip;
            _humSource.loop = true;
            _humSource.volume = 0f;
            _humSource.spatialBlend = 1f;
            _humSource.rolloffMode = AudioRolloffMode.Linear;
            _humSource.minDistance = 20f;
            _humSource.maxDistance = 400f;
            _humSource.playOnAwake = false;

            _alarmClip = BuildAlarmClip();
            _alarmSource = gameObject.AddComponent<AudioSource>();
            _alarmSource.clip = _alarmClip;
            _alarmSource.loop = true;
            _alarmSource.volume = 0f;
            _alarmSource.spatialBlend = 1f;
            _alarmSource.playOnAwake = false;
        }

        /// <summary>
        /// Blade-pass hum: fundamental at the rotor speed plus its harmonics, so
        /// pitch rises with rpm exactly like the real acoustic signature.
        /// </summary>
        private static AudioClip BuildHumClip()
        {
            const float duration = 2f;
            const float baseHz = 55f;
            int samples = Mathf.CeilToInt(SampleRate * duration);
            float[] data = new float[samples];

            for (int i = 0; i < samples; i++)
            {
                float t = (float)i / SampleRate;
                float value = 0.55f * Mathf.Sin(2f * Mathf.PI * baseHz * t);
                value += 0.25f * Mathf.Sin(2f * Mathf.PI * baseHz * 2f * t);
                value += 0.12f * Mathf.Sin(2f * Mathf.PI * baseHz * 3f * t);
                value += 0.06f * Mathf.Sin(2f * Mathf.PI * baseHz * 5f * t);
                data[i] = value * 0.5f;
            }

            AudioClip clip = AudioClip.Create("DrivetrainHum", samples, 1, SampleRate, false);
            clip.SetData(data, 0);
            return clip;
        }

        private static AudioClip BuildAlarmClip()
        {
            const float duration = 1f;
            const float toneHz = 880f;
            int samples = Mathf.CeilToInt(SampleRate * duration);
            float[] data = new float[samples];

            for (int i = 0; i < samples; i++)
            {
                float t = (float)i / SampleRate;
                float square = Mathf.Sign(Mathf.Sin(2f * Mathf.PI * toneHz * t));
                data[i] = square * 0.25f;
            }

            AudioClip clip = AudioClip.Create("CriticalAlarm", samples, 1, SampleRate, false);
            clip.SetData(data, 0);
            return clip;
        }

        /// <summary>
        /// Drive the hum from telemetry. Called every frame by the client, so a
        /// stalled or lost feed is audible as a dying tone.
        /// </summary>
        public void UpdateHum(float rotorRpm, float pitchAngle, bool connected)
        {
            if (_humSource == null)
            {
                return;
            }

            float rpmFactor = Mathf.Clamp01(rotorRpm / 12.6f);
            _humSource.pitch = Mathf.Clamp(0.35f + rpmFactor * 1.3f, 0.35f, 2.4f);
            _humSource.volume = connected ? _masterVolume * Mathf.Clamp01(0.25f + rpmFactor) * 0.6f : 0f;

            if (connected && !_humSource.isPlaying)
            {
                _humSource.Play();
            }
            else if (!connected && _humSource.isPlaying)
            {
                _humSource.Pause();
            }
        }

        public void StopAlarm()
        {
            if (_alarmSource != null && _alarmSource.isPlaying)
            {
                _alarmSource.Stop();
            }
        }

        private void OnDestroy()
        {
            if (_humClip != null)
            {
                Destroy(_humClip);
            }

            if (_alarmClip != null)
            {
                Destroy(_alarmClip);
            }
        }
    }
}