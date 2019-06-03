# flow past cylinder
import numpy as np
import os

from pysph.base.kernels import QuinticSpline
from pysph.sph.equation import Equation
from pysph.base.utils import get_particle_array
from pysph.solver.application import Application
from pysph.sph.scheme import SchemeChooser
from edac_free_of_NumberDensity import EDACScheme, SourceNumberDensity
from pysph.tools import geometry as G
from edac_free_of_NumberDensity import SolidWallPressureBC
from pysph.sph.bc.simple_inlet_outlet import SimpleInletOutlet
from pysph.sph.bc.inlet_outlet_manager import (
        InletInfo, OutletInfo)

# Geometric parameters
l_tunnel = 15.0
w_tunnel = 5.0
diameter = 2.0  # diameter of circle
center = l_tunnel / 3., 0.0  # center of circle
n_inlet = 10  # Number of inlet layers
n_outlet = 10  # Number of outlet layers
n_wall = 5
# Fluid mechanical/numerical parameters

rho = 1000
umax = 1.0
c0 = 10 * umax
p0 = rho * c0 * c0


class ExtrapolateUhat(Equation):
    def initialize(self, d_idx, d_uhat, d_wij):
        d_uhat[d_idx] = 0.0
        d_wij[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_uhat, s_uhat, d_wij, s_rho,
             d_au, d_av, d_aw, WIJ, XIJ):
        d_uhat[d_idx] += s_uhat[s_idx]*WIJ
        d_wij[d_idx] += WIJ

    def post_loop(self, d_idx, d_wij, d_uhat, d_rho):
        if d_wij[d_idx] > 1e-14:
            d_uhat[d_idx] /= d_wij[d_idx]


class ResetInletVelocity(Equation):
    def __init__(self, dest, sources, U, V, W):
        self.U = U
        self.V = V
        self.W = W

        super(ResetInletVelocity, self).__init__(dest, sources)

    def loop(self, d_idx, d_u, d_v, d_w, d_x, d_y, d_z, d_xn, d_yn, d_zn):
        d_u[d_idx] = self.U
        d_v[d_idx] = self.V
        d_w[d_idx] = self.W


class WindTunnel(Application):
    def pre_step(self, solver):
        solver.dump_output()

    def add_user_options(self, group):
        group.add_argument(
            "--re", action="store", type=float, dest="re", default=200,
            help="Reynolds number (defaults to 200)."
        )
        group.add_argument(
            "--hdx", action="store", type=float, dest="hdx", default=1.2,
            help="Ratio h/dx."
        )
        group.add_argument(
            "--nx", action="store", type=int, dest="nx", default=20,
            help="Number of points in 1D of the cylinder. (default 20)"
        )

    def consume_user_options(self):
        nx = self.options.nx
        re = self.options.re

        self.nu = nu = umax * diameter / re

        self.dx = dx = diameter / nx
        self.volume = dx * dx
        self.hdx = self.options.hdx

        h0 = self.hdx * self.dx
        dt_cfl = 0.25 * h0 / (c0 + umax)
        dt_viscous = 0.125 * h0**2 / nu

        self.dt = min(dt_cfl, dt_viscous)
        self.tf = 5.0

    def _create_fluid(self):
        dx = self.dx
        h0 = self.hdx * self.dx
        x, y = np.mgrid[dx / 2:l_tunnel:dx, -w_tunnel + dx/2:w_tunnel:dx]
        x, y = (np.ravel(t) for t in (x, y))
        one = np.ones_like(x)
        volume = dx * dx * one
        m = volume * rho
        fluid = get_particle_array(
            name='fluid', m=m, x=x, y=y, h=h0, u=umax, p=0.0,
            rho=rho
        )
        return fluid

    def _create_wall(self):
        dx = self.dx
        h0 = self.hdx * self.dx
        x0, y0 = np.mgrid[
            dx/2: l_tunnel+n_inlet*dx+n_outlet*dx: dx, dx/2: n_wall*dx: dx]
        x0 -= n_inlet*dx
        y0 -= n_wall*dx+w_tunnel
        x0 = np.ravel(x0)
        y0 = np.ravel(y0)

        x1 = np.copy(x0)
        y1 = np.copy(y0)
        y1 += n_wall*dx+2*w_tunnel
        x1 = np.ravel(x1)
        y1 = np.ravel(y1)
        x0 = np.concatenate((x0, x1))
        y0 = np.concatenate((y0, y1))
        volume = dx*dx
        wall = get_particle_array(
            name='wall', x=x0, y=y0, m=volume*rho, rho=rho, h=h0)
        return wall

    def _set_wall_normal(self, pa):
        props = ['xn', 'yn', 'zn']
        for p in props:
            pa.add_property(p)

        y = pa.y
        cond = y > 0.0
        pa.yn[cond] = 1.0
        cond = y < 0.0
        pa.yn[cond] = -1.0

    def _create_solid(self):
        dx = self.dx
        h0 = self.hdx * self.dx
        x, y = np.mgrid[dx / 2:l_tunnel:dx, -w_tunnel + dx/2:w_tunnel:dx]
        x, y = (np.ravel(t) for t in (x, y))
        xc, yc = center
        cond = (x - xc)**2 + (y - yc)**2 < (diameter/2*diameter/2)
        volume = dx*dx
        solid = get_particle_array(
            name='solid', x=x[cond].ravel(), y=y[cond].ravel(), m=volume*rho,
            rho=rho, h=h0
        )
        return solid

    def _create_outlet(self):
        dx = self.dx
        h0 = self.hdx * self.dx
        x, y = np.mgrid[dx/2:n_outlet * dx:dx,  -w_tunnel + dx/2:w_tunnel:dx]
        x, y = (np.ravel(t) for t in (x, y))
        x += l_tunnel
        one = np.ones_like(x)
        volume = dx * dx * one
        m = volume * rho
        outlet = get_particle_array(
            name='outlet', x=x, y=y, m=m, h=h0, u=umax,
            uhat=umax, p=0.0, rho=one * rho
        )
        return outlet

    def _create_inlet(self):
        dx = self.dx
        h0 = self.hdx * self.dx
        x, y = np.mgrid[dx / 2:n_inlet*dx:dx, -w_tunnel + dx/2:w_tunnel:dx]
        x, y = (np.ravel(t) for t in (x, y))
        x = x - n_inlet * dx
        one = np.ones_like(x)
        volume = one * dx * dx

        inlet = get_particle_array(
            name='inlet', x=x, y=y, m=volume * rho, h=h0, u=umax, rho=rho, p=0.0
        )
        return inlet

    def create_particles(self):
        fluid = self._create_fluid()
        solid = self._create_solid()
        outlet = self._create_outlet()
        inlet = self._create_inlet()
        wall = self._create_wall()
        G.remove_overlap_particles(fluid, solid, dx_solid=self.dx, dim=2)

        particles = [
            fluid, inlet, outlet, solid, wall
        ]

        self._set_wall_normal(wall)
        self.scheme.setup_properties(particles)

        return particles

    def create_scheme(self):
        '''Other scheme can be added here'''
        h0 = nu = None
        self.iom = self._create_inlet_outlet_manager()

        edac = EDACScheme(
            ['fluid'], ['solid'], dim=2, rho0=rho, c0=c0, h=h0,
            pb=None, nu=nu, alpha=0.2, inlet_outlet_manager=self.iom,
            inviscid_solids=['wall']
        )

        s = SchemeChooser(default='edac', edac=edac)

        return s

    def configure_scheme(self):
        scheme = self.scheme
        h0 = self.hdx * self.dx
        pfreq = 50
        kernel = QuinticSpline(dim=2)
        self.iom.update_dx(self.dx)
        if self.options.scheme == 'edac':
            scheme.configure(h=h0, nu=self.nu, pb=p0)

        scheme.configure_solver(kernel=kernel, tf=self.tf, dt=self.dt,
                                pfreq=pfreq, n_damp=0)

    def _create_inlet_outlet_manager(self):
        inleteqns = [
            ResetInletVelocity('inlet', [], U=umax, V=0.0, W=0.0),
            SolidWallPressureBC(dest='inlet', sources=['fluid']),
            ExtrapolateUhat('inlet', ['fluid'])
        ]

        inlet_info = InletInfo(
            pa_name='inlet', normal=[-1.0, 0.0, 0.0],
            refpoint=[0.0, 0.0, 0.0], equations=inleteqns
        )

        outlet_info = OutletInfo(
            pa_name='outlet', normal=[1.0, 0.0, 0.0],
            refpoint=[l_tunnel, 0.0, 0.0]
        )

        iom = SimpleInletOutlet(
            fluid_arrays=['fluid'], inletinfo=[inlet_info],
            outletinfo=[outlet_info]
        )

        return iom

    def create_inlet_outlet(self, particle_arrays):
        iom = self.iom
        io = iom.get_inlet_outlet(particle_arrays)
        return io

    def post_process(self, info_fname):
        self.read_info(info_fname)
        if len(self.output_files) == 0:
            return
        t, cd, cl = self._plot_force_vs_t()
        res = os.path.join(self.output_dir, 'results.npz')
        np.savez(res, t=t, cd=cd, cl=cl)

    def _get_force_evaluator(self):
        from pysph.solver.utils import load
        from pysph.base.kernels import QuinticSpline
        from pysph.tools.sph_evaluator import SPHEvaluator
        from pysph.sph.equation import Group
        from transport_velocity_free_of_NumberDensity import (
            SetWallVelocity, MomentumEquationPressureGradient,
            SolidWallNoSlipBC, MomentumEquationViscosity
        )
        data = load(self.output_files[0])
        solid = data['arrays']['solid']
        fluid = data['arrays']['fluid']

        prop = ['awhat', 'auhat', 'avhat', 'wg', 'vg', 'ug', 'uf', 'vf',
                'wf', 'wij', 'vmag']
        for p in prop:
            solid.add_property(p)
            fluid.add_property(p)
        equations = [
            Group(
                equations=[
                    SetWallVelocity(dest='fluid', sources=['solid']),
                ], real=False),
            Group(
                equations=[
                    # Pressure gradient terms
                    MomentumEquationPressureGradient(
                        dest='solid', sources=['fluid', 'solid'], pb=p0),
                    MomentumEquationViscosity(
                        dest='solid', sources=['fluid', 'solid'], nu=self.nu),
                    SolidWallNoSlipBC(
                        dest='solid', sources=['fluid'], nu=self.nu),
                    ], real=True),
        ]
        sph_eval = SPHEvaluator(
            arrays=[solid, fluid], equations=equations, dim=2,
            kernel=QuinticSpline(dim=2)
        )

        return sph_eval

    def _plot_force_vs_t(self):
        from pysph.solver.utils import iter_output
        prop = ['awhat', 'auhat', 'avhat', 'wg', 'vg', 'ug', 'uf', 'vf',
                'wf', 'wij', 'vmag']
        # We find the force of the solid on the fluid and the opposite of that
        # is the force on the solid. Note that the assumption is that the solid
        # is far from the inlet and outlet so those are ignored.
        sph_eval = self._get_force_evaluator()

        t, cd, cl = [], [], []
        for sd, arrays in iter_output(self.output_files):
            fluid = arrays['fluid']
            solid = arrays['solid']
            for p in prop:
                solid.add_property(p)
                fluid.add_property(p)
            t.append(sd['t']*diameter/umax)
            sph_eval.update_particle_arrays([solid, fluid])
            sph_eval.evaluate()
            cd.append(np.sum(solid.au*solid.m)/(0.5*rho*umax**2*diameter))
            cl.append(np.sum(solid.av*solid.m)/(0.5*rho*umax**2*diameter))
        t, cd, cl = list(map(np.asarray, (t, cd, cl)))
        # Now plot the results.
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib import pyplot as plt
        plt.figure()
        plt.plot(t, cd, label=r'$C_d$')
        plt.plot(t, cl, label=r'$C_l$')
        plt.xlabel(r'$t$')
        plt.ylabel('$C_d$/$C_l$')
        plt.legend()
        fig = os.path.join(self.output_dir, "lift_drag_vs_t.png")
        plt.savefig(fig, dpi=300)
        plt.close()
        return t, cd, cl


if __name__ == '__main__':
    app = WindTunnel()
    app.run()
    app.post_process(app.info_filename)
