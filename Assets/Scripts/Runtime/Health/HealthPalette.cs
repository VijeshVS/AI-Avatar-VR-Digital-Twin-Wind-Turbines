using UnityEngine;

namespace Vrar.Health
{
    /// <summary>
    /// Maps a 0..1 health score onto the avatar's perceptual channels: hue,
    /// emission, tremor and alarm state. Kept free of scene references so it can
    /// be unit tested.
    /// </summary>
    public struct HealthPalette
    {
        public static readonly Color Nominal = new Color(0.23f, 0.77f, 0.42f);
        public static readonly Color Watch = new Color(0.94f, 0.70f, 0.16f);
        public static readonly Color Alarm = new Color(0.88f, 0.23f, 0.18f);

        public const float WatchThreshold = 0.75f;
        public const float AlarmThreshold = 0.45f;

        /// <summary>Green above the watch line, amber between, red below.</summary>
        public static Color ColorFor(float health)
        {
            health = Mathf.Clamp01(health);
            if (health >= WatchThreshold)
            {
                return Color.Lerp(Watch, Nominal, Mathf.InverseLerp(WatchThreshold, 1f, health));
            }

            if (health >= AlarmThreshold)
            {
                return Color.Lerp(Alarm, Watch, Mathf.InverseLerp(AlarmThreshold, WatchThreshold, health));
            }

            return Color.Lerp(Alarm * 0.75f, Alarm, Mathf.InverseLerp(0f, AlarmThreshold, health));
        }

        /// <summary>0 when nominal, 1 when failed. Drives tremor and alarm volume.</summary>
        public static float Distress(float health) => 1f - Mathf.Clamp01(health);

        public static string StateFor(float health)
        {
            if (health >= WatchThreshold)
            {
                return "healthy";
            }

            return health >= AlarmThreshold ? "warning" : "critical";
        }
    }
}